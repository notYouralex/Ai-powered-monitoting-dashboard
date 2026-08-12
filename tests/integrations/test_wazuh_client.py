import asyncio

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import IntegrationError
from app.integrations.wazuh.client import WazuhClient


def make_settings(**overrides) -> Settings:
    values = {
        "app_env": "test",
        "app_secret_key": "t" * 48,
        "database_url": "sqlite:///test.db",
        "wazuh_base_url": "https://wazuh.internal:55000",
        "wazuh_username": "dashboard-reader",
        "wazuh_password": "fake-wazuh-password",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_from_settings_rejects_unconfigured_wazuh() -> None:
    settings = make_settings(
        wazuh_base_url=None,
        wazuh_username=None,
        wazuh_password=None,
    )

    with pytest.raises(IntegrationError) as exc_info:
        WazuhClient.from_settings(settings)

    assert exc_info.value.source == "wazuh"
    assert exc_info.value.code == "SOURCE_NOT_CONFIGURED"
    assert exc_info.value.retryable is False


def test_list_agents_authenticates_and_normalizes_results() -> None:
    async def run() -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/security/user/authenticate":
                assert request.method == "POST"
                assert request.headers["Authorization"].startswith("Basic ")
                return httpx.Response(
                    200,
                    json={"data": {"token": "fake-jwt-token"}, "error": 0},
                )

            assert request.url.path == "/agents"
            assert request.method == "GET"
            assert request.headers["Authorization"] == "Bearer fake-jwt-token"
            assert request.url.params["limit"] == "500"
            assert request.url.params["offset"] == "0"
            return httpx.Response(
                200,
                json={
                    "data": {
                        "affected_items": [
                            {
                                "id": "001",
                                "name": "web-01",
                                "ip": "10.0.0.11",
                                "status": "active",
                                "manager": "wazuh-manager",
                                "node_name": "node01",
                                "group": ["linux", "production"],
                                "lastKeepAlive": "2026-08-10T04:00:00Z",
                                "os": {
                                    "name": "Ubuntu",
                                    "version": "24.04.3 LTS",
                                    "platform": "ubuntu",
                                    "arch": "x86_64",
                                },
                            }
                        ],
                        "total_affected_items": 1,
                        "total_failed_items": 0,
                        "failed_items": [],
                    },
                    "error": 0,
                },
            )

        client = WazuhClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )
        agents = await client.list_agents()

        assert len(requests) == 2
        assert len(agents) == 1
        agent = agents[0]
        assert agent.agent_id == "001"
        assert agent.name == "web-01"
        assert agent.ip == "10.0.0.11"
        assert agent.status == "active"
        assert agent.os_name == "Ubuntu"
        assert agent.os_version == "24.04.3 LTS"
        assert agent.os_platform == "ubuntu"
        assert agent.os_arch == "x86_64"
        assert agent.groups == ["linux", "production"]
        assert agent.last_keep_alive is not None

    asyncio.run(run())


def test_list_agents_pages_until_total_is_reached() -> None:
    async def run() -> None:
        offsets: list[int] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/security/user/authenticate":
                return httpx.Response(200, json={"data": {"token": "fake-jwt"}, "error": 0})

            offset = int(request.url.params["offset"])
            offsets.append(offset)
            item = {
                "id": f"{offset + 1:03d}",
                "name": f"agent-{offset + 1}",
                "status": "active",
            }
            return httpx.Response(
                200,
                json={
                    "data": {
                        "affected_items": [item],
                        "total_affected_items": 2,
                        "total_failed_items": 0,
                        "failed_items": [],
                    },
                    "error": 0,
                },
            )

        client = WazuhClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )
        agents = await client.list_agents()

        assert offsets == [0, 1]
        assert [agent.agent_id for agent in agents] == ["001", "002"]

    asyncio.run(run())


def test_unknown_agent_status_is_normalized_without_rejecting_record() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/security/user/authenticate":
                return httpx.Response(200, json={"data": {"token": "fake-jwt"}, "error": 0})
            return httpx.Response(
                200,
                json={
                    "data": {
                        "affected_items": [
                            {"id": "001", "name": "agent-1", "status": "future_status"}
                        ],
                        "total_affected_items": 1,
                        "total_failed_items": 0,
                        "failed_items": [],
                    },
                    "error": 0,
                },
            )

        client = WazuhClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )
        agents = await client.list_agents()
        assert agents[0].status == "unknown"

    asyncio.run(run())


def test_authentication_failure_maps_to_safe_source_error() -> None:
    async def run() -> None:
        fake_password = "fake-password-that-must-not-leak"

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"title": fake_password})

        client = WazuhClient.from_settings(
            make_settings(wazuh_password=fake_password),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.list_agents()

        exc = exc_info.value
        assert exc.code == "SOURCE_AUTH_FAILED"
        assert exc.retryable is False
        assert fake_password not in str(exc)
        assert fake_password not in repr(exc)

    asyncio.run(run())


def test_agent_rate_limit_maps_after_bounded_shared_retries(monkeypatch) -> None:
    async def run() -> None:
        agent_attempts = 0
        delays: list[float] = []

        async def fake_sleep(delay: float) -> None:
            delays.append(delay)

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal agent_attempts
            if request.url.path == "/security/user/authenticate":
                return httpx.Response(200, json={"data": {"token": "fake-jwt"}, "error": 0})
            agent_attempts += 1
            return httpx.Response(429, json={"error": 429})

        monkeypatch.setattr("app.core.http.asyncio.sleep", fake_sleep)
        client = WazuhClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.list_agents()

        assert agent_attempts == 3
        assert delays == [0.25, 0.5]
        assert exc_info.value.code == "SOURCE_RATE_LIMITED"
        assert exc_info.value.retryable is True

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
        client = WazuhClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.list_agents()

        assert attempts == 1
        assert delays == []
        assert exc_info.value.code == "SOURCE_UNAVAILABLE"
        assert exc_info.value.retryable is True

    asyncio.run(run())


def test_invalid_agent_record_maps_to_bad_response() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/security/user/authenticate":
                return httpx.Response(200, json={"data": {"token": "fake-jwt"}, "error": 0})
            return httpx.Response(
                200,
                json={
                    "data": {
                        "affected_items": [{"id": "001", "name": None, "status": "active"}],
                        "total_affected_items": 1,
                        "total_failed_items": 0,
                        "failed_items": [],
                    },
                    "error": 0,
                },
            )

        client = WazuhClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.list_agents()

        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"
        assert exc_info.value.retryable is False

    asyncio.run(run())


def test_malformed_agents_payload_maps_to_bad_response_without_raw_body() -> None:
    async def run() -> None:
        raw_marker = "raw-source-marker-must-not-leak"

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/security/user/authenticate":
                return httpx.Response(200, json={"data": {"token": "fake-jwt"}, "error": 0})
            return httpx.Response(200, text=raw_marker)

        client = WazuhClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.list_agents()

        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"
        assert exc_info.value.retryable is False
        assert raw_marker not in str(exc_info.value)
        assert raw_marker not in repr(exc_info.value)

    asyncio.run(run())
