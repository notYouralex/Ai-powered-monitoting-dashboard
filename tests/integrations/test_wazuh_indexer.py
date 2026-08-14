import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import IntegrationError
from app.integrations.wazuh.indexer_client import WazuhIndexerClient


START = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
END = datetime(2026, 8, 10, 1, 0, tzinfo=timezone.utc)


def make_settings(**overrides) -> Settings:
    values = {
        "app_env": "test",
        "app_secret_key": "t" * 48,
        "database_url": "sqlite:///test.db",
        "wazuh_indexer_base_url": "https://wazuh-indexer.internal:9200",
        "wazuh_indexer_username": "dashboard-reader",
        "wazuh_indexer_password": "fake-indexer-password",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_from_settings_rejects_unconfigured_indexer() -> None:
    settings = make_settings(
        wazuh_indexer_base_url=None,
        wazuh_indexer_username=None,
        wazuh_indexer_password=None,
    )

    with pytest.raises(IntegrationError) as exc_info:
        WazuhIndexerClient.from_settings(settings)

    assert exc_info.value.code == "SOURCE_NOT_CONFIGURED"
    assert exc_info.value.source == "wazuh"
    assert exc_info.value.retryable is False


def test_search_alerts_uses_bounded_read_only_query_and_normalizes_response() -> None:
    async def run() -> None:
        seen_request: httpx.Request | None = None
        seen_body: dict | None = None

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal seen_request, seen_body
            seen_request = request
            seen_body = __import__("json").loads(request.content)
            return httpx.Response(
                200,
                json={
                    "took": 7,
                    "timed_out": False,
                    "_shards": {"total": 1, "successful": 1, "skipped": 0, "failed": 0},
                    "hits": {
                        "total": {"value": 3, "relation": "eq"},
                        "max_score": None,
                        "hits": [
                            {
                                "_source": {
                                    "timestamp": "2026-08-10T00:55:00.000+00:00",
                                    "rule": {
                                        "id": "5710",
                                        "level": 12,
                                        "description": "SSH authentication failed.",
                                        "groups": ["syslog", "sshd"],
                                    },
                                    "agent": {"id": "001", "name": "web-01"},
                                }
                            }
                        ],
                    },
                    "aggregations": {
                        "severity_levels": {
                            "buckets": [
                                {"key": 12, "doc_count": 2},
                                {"key": 15, "doc_count": 1},
                            ]
                        },
                        "top_agents": {
                            "buckets": [
                                {"key": "web-01", "doc_count": 2},
                                {"key": "db-01", "doc_count": 1},
                            ]
                        },
                        "top_alerts": {
                            "buckets": [
                                {"key": "SSH authentication failed.", "doc_count": 2},
                                {"key": "Service stopped.", "doc_count": 1},
                            ]
                        },
                        "fim": {
                            "doc_count": 2,
                            "events": {
                                "buckets": [
                                    {"key": "added", "doc_count": 1},
                                    {"key": "modified", "doc_count": 1},
                                ]
                            },
                            "top_agents": {
                                "buckets": [{"key": "web-01", "doc_count": 2}]
                            },
                        },
                        "mitre": {
                            "doc_count": 2,
                            "tactics": {
                                "buckets": [{"key": "Credential Access", "doc_count": 2}]
                            },
                            "techniques": {
                                "buckets": [{"key": "Password Guessing", "doc_count": 2}]
                            },
                            "top_agents": {
                                "buckets": [{"key": "web-01", "doc_count": 2}]
                            },
                        },
                        "alert_trend": {
                            "buckets": [
                                {
                                    "key_as_string": "2026-08-10T00:00:00.000Z",
                                    "key": 1786320000000,
                                    "doc_count": 3,
                                }
                            ]
                        },
                    },
                },
            )

        client = WazuhIndexerClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )
        result = await client.search_alerts(START, END, trend_interval="1h")

        assert seen_request is not None
        assert seen_request.method == "POST"
        assert seen_request.url.path == "/wazuh-alerts*/_search"
        assert seen_request.headers["Authorization"].startswith("Basic ")
        assert seen_request.url.params["ignore_unavailable"] == "true"
        assert seen_request.url.params["allow_no_indices"] == "true"
        assert seen_request.url.params["allow_partial_search_results"] == "false"

        assert seen_body is not None
        assert seen_body["size"] == 50
        assert seen_body["track_total_hits"] is True
        assert "full_log" not in seen_body["_source"]
        assert seen_body["query"]["range"]["timestamp"]["gte"] == START.isoformat()
        assert seen_body["query"]["range"]["timestamp"]["lte"] == END.isoformat()
        assert seen_body["aggs"]["alert_trend"]["date_histogram"]["fixed_interval"] == "1h"
        assert seen_body["aggs"]["top_alerts"]["terms"]["size"] == 5
        assert seen_body["aggs"]["fim"]["filter"] == {"exists": {"field": "syscheck.path"}}
        assert seen_body["aggs"]["mitre"]["filter"] == {
            "exists": {"field": "rule.mitre.id"}
        }

        assert result.total_alerts == 3
        assert result.severity_levels == {12: 2, 15: 1}
        assert result.top_agents[0].name == "web-01"
        assert result.top_agents[0].count == 2
        assert result.top_alerts[0].name == "SSH authentication failed."
        assert result.top_alerts[0].count == 2
        assert result.fim.total == 2
        assert result.fim.added == 1
        assert result.fim.modified == 1
        assert result.fim.deleted == 0
        assert result.fim.top_agents[0].name == "web-01"
        assert result.mitre.total == 2
        assert result.mitre.tactics[0].name == "Credential Access"
        assert result.mitre.techniques[0].name == "Password Guessing"
        assert result.trend[0].count == 3
        assert result.alerts[0].rule_id == "5710"
        assert result.alerts[0].rule_level == 12
        assert result.alerts[0].agent_name == "web-01"
        assert result.alerts[0].groups == ["syslog", "sshd"]

    asyncio.run(run())


def test_search_alerts_accepts_empty_result() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "timed_out": False,
                    "_shards": {"failed": 0},
                    "hits": {"total": {"value": 0, "relation": "eq"}, "hits": []},
                    "aggregations": {
                        "severity_levels": {"buckets": []},
                        "top_agents": {"buckets": []},
                        "top_alerts": {"buckets": []},
                        "fim": {
                            "doc_count": 0,
                            "events": {"buckets": []},
                            "top_agents": {"buckets": []},
                        },
                        "mitre": {
                            "doc_count": 0,
                            "tactics": {"buckets": []},
                            "techniques": {"buckets": []},
                            "top_agents": {"buckets": []},
                        },
                        "alert_trend": {"buckets": []},
                    },
                },
            )

        client = WazuhIndexerClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )
        result = await client.search_alerts(START, END, trend_interval="1h")

        assert result.total_alerts == 0
        assert result.alerts == []
        assert result.severity_levels == {}
        assert result.top_agents == []
        assert result.top_alerts == []
        assert result.fim.total == 0
        assert result.mitre.total == 0
        assert result.trend == []

    asyncio.run(run())


def test_search_vulnerabilities_uses_current_state_index_and_normalizes_response() -> None:
    async def run() -> None:
        seen_request: httpx.Request | None = None
        seen_body: dict | None = None

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal seen_request, seen_body
            seen_request = request
            seen_body = __import__("json").loads(request.content)
            return httpx.Response(
                200,
                json={
                    "timed_out": False,
                    "_shards": {"failed": 0},
                    "hits": {
                        "total": {"value": 2, "relation": "eq"},
                        "hits": [
                            {
                                "_source": {
                                    "agent": {"id": "001", "name": "web-01"},
                                    "package": {"name": "openssl", "version": "3.0.1"},
                                    "vulnerability": {
                                        "id": "CVE-2026-0001",
                                        "severity": "Critical",
                                        "detected_at": "2026-08-10T00:50:00.000Z",
                                        "score": {"base": 9.8},
                                        "description": "Example OpenSSL vulnerability.",
                                    },
                                }
                            }
                        ],
                    },
                    "aggregations": {
                        "severity": {
                            "buckets": [
                                {"key": "Critical", "doc_count": 1},
                                {"key": "-", "doc_count": 1},
                            ]
                        },
                        "unique_cves": {"value": 2},
                        "affected_agents": {"value": 1},
                        "top_agents": {
                            "buckets": [{"key": "web-01", "doc_count": 2}]
                        },
                    },
                },
            )

        client = WazuhIndexerClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )
        result = await client.search_vulnerabilities()

        assert seen_request is not None
        assert seen_request.method == "POST"
        assert seen_request.url.path == "/wazuh-states-vulnerabilities*/_search"
        assert seen_body is not None
        assert seen_body["size"] == 20
        assert seen_body["track_total_hits"] is True
        assert seen_body["sort"] == [{"vulnerability.detected_at": {"order": "desc"}}]
        assert "vulnerability.reference" not in seen_body["_source"]

        assert result.total == 2
        assert result.unique_cves == 2
        assert result.affected_agents == 1
        assert [(item.name, item.count) for item in result.by_severity] == [
            ("Critical", 1),
            ("Unspecified", 1),
        ]
        assert result.top_agents[0].name == "web-01"
        assert result.recent[0].vulnerability_id == "CVE-2026-0001"
        assert result.recent[0].severity == "Critical"
        assert result.recent[0].score == 9.8
        assert result.recent[0].agent_name == "web-01"
        assert result.recent[0].package_name == "openssl"

    asyncio.run(run())


def test_rate_limit_maps_after_shared_retries(monkeypatch) -> None:
    async def run() -> None:
        attempts = 0
        delays: list[float] = []

        async def fake_sleep(delay: float) -> None:
            delays.append(delay)

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(429, json={"error": "rate limited"})

        monkeypatch.setattr("app.core.http.asyncio.sleep", fake_sleep)
        client = WazuhIndexerClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.search_alerts(START, END, trend_interval="1h")

        assert attempts == 3
        assert delays == [0.25, 0.5]
        assert exc_info.value.code == "SOURCE_RATE_LIMITED"
        assert exc_info.value.retryable is True

    asyncio.run(run())


def test_authentication_failure_does_not_leak_indexer_password() -> None:
    async def run() -> None:
        password = "fake-indexer-password-must-not-leak"

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": password})

        client = WazuhIndexerClient.from_settings(
            make_settings(wazuh_indexer_password=password),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.search_alerts(START, END, trend_interval="1h")

        assert exc_info.value.code == "SOURCE_AUTH_FAILED"
        assert exc_info.value.retryable is False
        assert password not in str(exc_info.value)
        assert password not in repr(exc_info.value)

    asyncio.run(run())


def test_connection_failure_maps_to_source_unavailable(monkeypatch) -> None:
    async def run() -> None:
        attempts = 0
        delays: list[float] = []

        async def fake_sleep(delay: float) -> None:
            delays.append(delay)

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            raise httpx.ConnectError("connection failed", request=request)

        monkeypatch.setattr("app.core.http.asyncio.sleep", fake_sleep)
        client = WazuhIndexerClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.search_alerts(START, END, trend_interval="1h")

        assert attempts == 3
        assert delays == [0.25, 0.5]
        assert exc_info.value.code == "SOURCE_UNAVAILABLE"
        assert exc_info.value.retryable is True

    asyncio.run(run())


def test_timed_out_search_maps_to_source_unavailable() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "timed_out": True,
                    "_shards": {"failed": 0},
                    "hits": {"total": {"value": 0}, "hits": []},
                    "aggregations": {},
                },
            )

        client = WazuhIndexerClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.search_alerts(START, END, trend_interval="1h")

        assert exc_info.value.code == "SOURCE_UNAVAILABLE"
        assert exc_info.value.retryable is True

    asyncio.run(run())


def test_failed_shards_map_to_bad_response() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "timed_out": False,
                    "_shards": {"failed": 1},
                    "hits": {"total": {"value": 0}, "hits": []},
                    "aggregations": {},
                },
            )

        client = WazuhIndexerClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.search_alerts(START, END, trend_interval="1h")

        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"
        assert exc_info.value.retryable is False

    asyncio.run(run())


def test_malformed_payload_maps_to_bad_response_without_raw_body() -> None:
    async def run() -> None:
        marker = "raw-indexer-body-must-not-leak"

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=marker)

        client = WazuhIndexerClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.search_alerts(START, END, trend_interval="1h")

        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"
        assert marker not in str(exc_info.value)
        assert marker not in repr(exc_info.value)

    asyncio.run(run())
