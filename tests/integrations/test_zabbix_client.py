import asyncio
import json
from pathlib import Path
import re

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import IntegrationError
from app.integrations.zabbix.client import ZabbixClient


def make_settings(**overrides) -> Settings:
    values = {
        "app_env": "test",
        "app_secret_key": "t" * 48,
        "database_url": "sqlite:///test.db",
        "zabbix_base_url": "https://zabbix.internal/api_jsonrpc.php",
        "zabbix_api_token": "fake-zabbix-token",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_from_settings_rejects_unconfigured_zabbix() -> None:
    settings = make_settings(zabbix_base_url=None, zabbix_api_token=None)

    with pytest.raises(IntegrationError) as exc_info:
        ZabbixClient.from_settings(settings)

    assert exc_info.value.source == "zabbix"
    assert exc_info.value.code == "SOURCE_NOT_CONFIGURED"
    assert exc_info.value.retryable is False


def test_list_hosts_uses_read_only_host_get_and_normalizes_interfaces() -> None:
    async def run() -> None:
        seen: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            body = json.loads(request.content)
            assert request.method == "POST"
            assert request.url == httpx.URL("https://zabbix.internal/api_jsonrpc.php")
            assert request.headers["Content-Type"] == "application/json-rpc"
            assert request.headers["Authorization"] == "Bearer fake-zabbix-token"
            assert "fake-zabbix-token" not in request.content.decode()
            assert body["jsonrpc"] == "2.0"
            assert body["method"] == "host.get"
            assert body["params"]["limit"] == 5001
            assert body["params"]["output"] == [
                "hostid",
                "host",
                "name",
                "status",
                "maintenance_status",
            ]
            assert body["params"]["selectInterfaces"] == [
                "interfaceid",
                "type",
                "main",
                "useip",
                "ip",
                "dns",
                "available",
            ]
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": [
                        {
                            "hostid": "10001",
                            "host": "web-01.internal",
                            "name": "Web 01",
                            "status": "0",
                            "maintenance_status": "1",
                            "interfaces": [
                                {
                                    "interfaceid": "10",
                                    "type": "1",
                                    "main": "1",
                                    "useip": "1",
                                    "ip": "10.0.0.11",
                                    "dns": "",
                                    "available": "1",
                                },
                                {
                                    "interfaceid": "11",
                                    "type": "2",
                                    "main": "0",
                                    "useip": "0",
                                    "ip": "",
                                    "dns": "web-01.internal",
                                    "available": "2",
                                },
                            ],
                        }
                    ],
                },
            )

        client = ZabbixClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )
        hosts = await client.list_hosts()

        assert len(seen) == 1
        assert len(hosts) == 1
        host = hosts[0]
        assert host.host_id == "10001"
        assert host.technical_name == "web-01.internal"
        assert host.name == "Web 01"
        assert host.enabled is True
        assert host.in_maintenance is True
        assert host.interfaces[0].type == "agent"
        assert host.interfaces[0].availability == "available"
        assert host.interfaces[0].address == "10.0.0.11"
        assert host.interfaces[1].type == "snmp"
        assert host.interfaces[1].availability == "unavailable"
        assert host.interfaces[1].address == "web-01.internal"

    asyncio.run(run())


def _host_record(*, host_id: str = "10001", interfaces=None, status: str = "0") -> dict:
    return {
        "hostid": host_id,
        "host": f"host-{host_id}",
        "name": f"Host {host_id}",
        "status": status,
        "maintenance_status": "0",
        "interfaces": [] if interfaces is None else interfaces,
    }


def test_malformed_json_maps_to_bad_response_without_raw_body_leakage() -> None:
    async def run() -> None:
        raw_marker = "raw-zabbix-marker-must-not-leak"

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=raw_marker)

        client = ZabbixClient.from_settings(
            make_settings(), transport=httpx.MockTransport(handler)
        )
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_hosts()

        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"
        assert exc_info.value.retryable is False
        assert raw_marker not in str(exc_info.value)
        assert raw_marker not in repr(exc_info.value)

    asyncio.run(run())


def test_mismatched_jsonrpc_id_maps_to_bad_response() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 999, "result": []})

        client = ZabbixClient.from_settings(
            make_settings(), transport=httpx.MockTransport(handler)
        )
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_hosts()

        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"

    asyncio.run(run())


def test_wrong_jsonrpc_version_maps_to_bad_response() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"jsonrpc": "1.0", "id": 1, "result": []})

        client = ZabbixClient.from_settings(
            make_settings(), transport=httpx.MockTransport(handler)
        )
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_hosts()

        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"

    asyncio.run(run())


def test_http_authentication_failure_maps_to_safe_source_error() -> None:
    async def run() -> None:
        fake_token = "fake-zabbix-token-that-must-not-leak"

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"token": fake_token})

        client = ZabbixClient.from_settings(
            make_settings(zabbix_api_token=fake_token),
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_hosts()

        assert exc_info.value.code == "SOURCE_AUTH_FAILED"
        assert exc_info.value.retryable is False
        assert fake_token not in str(exc_info.value)
        assert fake_token not in repr(exc_info.value)

    asyncio.run(run())


def test_jsonrpc_authorization_failure_maps_without_source_error_leakage() -> None:
    async def run() -> None:
        source_detail = "Not authorized. internal-sensitive-marker"

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {
                        "code": -32602,
                        "message": "Invalid params.",
                        "data": source_detail,
                    },
                },
            )

        client = ZabbixClient.from_settings(
            make_settings(), transport=httpx.MockTransport(handler)
        )
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_hosts()

        assert exc_info.value.code == "SOURCE_AUTH_FAILED"
        assert exc_info.value.retryable is False
        assert source_detail not in str(exc_info.value)
        assert source_detail not in repr(exc_info.value)

    asyncio.run(run())


def test_non_auth_jsonrpc_error_maps_to_bad_response() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {
                        "code": -32602,
                        "message": "Invalid params.",
                        "data": "Some other source detail",
                    },
                },
            )

        client = ZabbixClient.from_settings(
            make_settings(), transport=httpx.MockTransport(handler)
        )
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_hosts()

        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"
        assert exc_info.value.retryable is False

    asyncio.run(run())


def test_rate_limit_maps_after_bounded_shared_retries(monkeypatch) -> None:
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
        client = ZabbixClient.from_settings(
            make_settings(), transport=httpx.MockTransport(handler)
        )
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_hosts()

        assert attempts == 3
        assert delays == [0.25, 0.5]
        assert exc_info.value.code == "SOURCE_RATE_LIMITED"
        assert exc_info.value.retryable is True

    asyncio.run(run())


def test_server_failure_maps_after_bounded_shared_retries(monkeypatch) -> None:
    async def run() -> None:
        attempts = 0
        delays: list[float] = []

        async def fake_sleep(delay: float) -> None:
            delays.append(delay)

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(503, json={"error": "temporarily unavailable"})

        monkeypatch.setattr("app.core.http.asyncio.sleep", fake_sleep)
        client = ZabbixClient.from_settings(
            make_settings(), transport=httpx.MockTransport(handler)
        )
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_hosts()

        assert attempts == 3
        assert delays == [0.25, 0.5]
        assert exc_info.value.code == "SOURCE_UNAVAILABLE"
        assert exc_info.value.retryable is True

    asyncio.run(run())


def test_connection_failure_maps_after_bounded_shared_retries(monkeypatch) -> None:
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
        client = ZabbixClient.from_settings(
            make_settings(), transport=httpx.MockTransport(handler)
        )
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_hosts()

        assert attempts == 3
        assert delays == [0.25, 0.5]
        assert exc_info.value.code == "SOURCE_UNAVAILABLE"
        assert exc_info.value.retryable is True

    asyncio.run(run())


def test_host_result_bound_rejects_sentinel_record() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": [_host_record(host_id=str(index)) for index in range(5001)],
                },
            )

        client = ZabbixClient.from_settings(
            make_settings(), transport=httpx.MockTransport(handler)
        )
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_hosts()

        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"

    asyncio.run(run())


def test_interface_bound_rejects_more_than_32_interfaces() -> None:
    async def run() -> None:
        interfaces = [
            {
                "interfaceid": str(index),
                "type": "1",
                "main": "0",
                "useip": "1",
                "ip": f"10.0.0.{index}",
                "dns": "",
                "available": "1",
            }
            for index in range(33)
        ]

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": [_host_record(interfaces=interfaces)],
                },
            )

        client = ZabbixClient.from_settings(
            make_settings(), transport=httpx.MockTransport(handler)
        )
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_hosts()

        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"

    asyncio.run(run())


def test_invalid_host_status_maps_to_bad_response() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": [_host_record(status="2")],
                },
            )

        client = ZabbixClient.from_settings(
            make_settings(), transport=httpx.MockTransport(handler)
        )
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_hosts()

        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"

    asyncio.run(run())


def test_missing_required_host_field_maps_to_bad_response() -> None:
    async def run() -> None:
        invalid = _host_record()
        invalid.pop("hostid")

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": body["id"], "result": [invalid]},
            )

        client = ZabbixClient.from_settings(
            make_settings(), transport=httpx.MockTransport(handler)
        )
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_hosts()

        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"

    asyncio.run(run())


def test_empty_result_is_valid() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": body["id"], "result": []}
            )

        client = ZabbixClient.from_settings(
            make_settings(), transport=httpx.MockTransport(handler)
        )
        assert await client.list_hosts() == []

    asyncio.run(run())


def test_unknown_future_interface_values_normalize_safely() -> None:
    async def run() -> None:
        interface = {
            "interfaceid": "10",
            "type": "9",
            "main": "1",
            "useip": "1",
            "ip": "10.0.0.10",
            "dns": "",
            "available": "9",
        }

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": [_host_record(interfaces=[interface])],
                },
            )

        client = ZabbixClient.from_settings(
            make_settings(), transport=httpx.MockTransport(handler)
        )
        hosts = await client.list_hosts()
        assert hosts[0].interfaces[0].type == "unknown"
        assert hosts[0].interfaces[0].availability == "unknown"

    asyncio.run(run())


def test_public_client_exposes_no_mutation_or_generic_call_methods() -> None:
    public = {name for name in dir(ZabbixClient) if not name.startswith("_")}

    assert "create" not in public
    assert "update" not in public
    assert "delete" not in public
    assert "request" not in public
    assert "call" not in public
    assert "list_hosts" in public
    assert "list_active_problems" in public


def test_list_active_problems_empty_result_skips_trigger_get() -> None:
    async def run() -> None:
        methods: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            methods.append(body["method"])
            assert request.method == "POST"
            assert request.url == httpx.URL("https://zabbix.internal/api_jsonrpc.php")
            assert request.headers["Content-Type"] == "application/json-rpc"
            assert request.headers["Authorization"] == "Bearer fake-zabbix-token"
            assert "fake-zabbix-token" not in request.content.decode()
            assert body["jsonrpc"] == "2.0"
            assert body["method"] == "problem.get"
            assert body["params"] == {
                "output": [
                    "eventid",
                    "objectid",
                    "clock",
                    "name",
                    "acknowledged",
                    "severity",
                    "suppressed",
                ],
                "recent": False,
                "source": 0,
                "object": 0,
                "sortfield": "eventid",
                "sortorder": "DESC",
                "limit": 1001,
            }
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": body["id"], "result": []},
            )

        client = ZabbixClient.from_settings(
            make_settings(), transport=httpx.MockTransport(handler)
        )

        assert await client.list_active_problems() == []
        assert methods == ["problem.get"]

    asyncio.run(run())


def _problem_record(
    *,
    event_id: str = "7001",
    trigger_id: str = "9001",
    clock: str = "1723521600",
    name: str = "CPU load is high",
    acknowledged: str = "0",
    severity: str = "4",
    suppressed: str = "0",
) -> dict:
    return {
        "eventid": event_id,
        "objectid": trigger_id,
        "clock": clock,
        "name": name,
        "acknowledged": acknowledged,
        "severity": severity,
        "suppressed": suppressed,
    }


def _trigger_host_record(
    *,
    host_id: str = "10001",
    technical_name: str = "web-01.internal",
    name: str = "Web 01",
) -> dict:
    return {"hostid": host_id, "host": technical_name, "name": name}


def _trigger_record(*, trigger_id: str = "9001", hosts=None) -> dict:
    return {
        "triggerid": trigger_id,
        "hosts": [_trigger_host_record()] if hosts is None else hosts,
    }


def test_list_active_problems_resolves_trigger_hosts_and_normalizes_records() -> None:
    async def run() -> None:
        methods: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            methods.append(body["method"])
            if body["method"] == "problem.get":
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": [
                            _problem_record(event_id="7001", trigger_id="9001", severity="4", acknowledged="0", suppressed="1"),
                            _problem_record(event_id="7002", trigger_id="9001", clock="1723521660", severity="2", acknowledged="1", suppressed="0"),
                        ],
                    },
                )

            assert body["method"] == "trigger.get"
            assert body["params"] == {
                "triggerids": ["9001"],
                "output": ["triggerid"],
                "selectHosts": ["hostid", "host", "name"],
            }
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": body["id"], "result": [_trigger_record()]},
            )

        client = ZabbixClient.from_settings(make_settings(), transport=httpx.MockTransport(handler))
        problems = await client.list_active_problems()

        assert methods == ["problem.get", "trigger.get"]
        assert [problem.event_id for problem in problems] == ["7001", "7002"]
        assert problems[0].trigger_id == "9001"
        assert problems[0].severity == "high"
        assert problems[1].severity == "warning"
        assert problems[0].acknowledged is False
        assert problems[0].suppressed is True
        assert problems[1].acknowledged is True
        assert problems[1].suppressed is False
        assert problems[0].started_at.tzinfo is not None
        assert problems[0].started_at.utcoffset().total_seconds() == 0
        assert problems[0].hosts[0].host_id == "10001"
        assert problems[0].hosts[0].technical_name == "web-01.internal"
        assert problems[0].hosts[0].name == "Web 01"
        assert problems[1].hosts == problems[0].hosts

    asyncio.run(run())


@pytest.mark.parametrize(
    ("source_severity", "expected"),
    [
        ("0", "not_classified"),
        ("1", "information"),
        ("2", "warning"),
        ("3", "average"),
        ("4", "high"),
        ("5", "disaster"),
        ("9", "unknown"),
    ],
)
def test_active_problem_severity_normalizes(source_severity: str, expected: str) -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            result = [_problem_record(severity=source_severity)] if body["method"] == "problem.get" else [_trigger_record()]
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

        client = ZabbixClient.from_settings(make_settings(), transport=httpx.MockTransport(handler))
        problems = await client.list_active_problems()
        assert problems[0].severity == expected

    asyncio.run(run())


def test_active_problem_result_bound_rejects_sentinel_record() -> None:
    async def run() -> None:
        methods: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            methods.append(body["method"])
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": body["id"], "result": [_problem_record(event_id=str(index)) for index in range(1001)]},
            )

        client = ZabbixClient.from_settings(make_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_active_problems()
        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"
        assert methods == ["problem.get"]

    asyncio.run(run())


@pytest.mark.parametrize("field", ["acknowledged", "suppressed"])
def test_invalid_active_problem_binary_field_maps_to_bad_response(field: str) -> None:
    async def run() -> None:
        problem = _problem_record()
        problem[field] = "2"

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            result = [problem] if body["method"] == "problem.get" else [_trigger_record()]
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

        client = ZabbixClient.from_settings(make_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_active_problems()
        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"

    asyncio.run(run())


@pytest.mark.parametrize("field", ["eventid", "objectid", "name"])
def test_missing_required_active_problem_field_maps_to_bad_response(field: str) -> None:
    async def run() -> None:
        problem = _problem_record()
        problem.pop(field)

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            result = [problem] if body["method"] == "problem.get" else [_trigger_record()]
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

        client = ZabbixClient.from_settings(make_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_active_problems()
        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"

    asyncio.run(run())


@pytest.mark.parametrize("field", ["eventid", "objectid", "name"])
def test_blank_required_active_problem_field_maps_to_bad_response(field: str) -> None:
    async def run() -> None:
        problem = _problem_record()
        problem[field] = "   "

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            result = [problem] if body["method"] == "problem.get" else [_trigger_record()]
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

        client = ZabbixClient.from_settings(make_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_active_problems()
        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"

    asyncio.run(run())


def test_invalid_active_problem_clock_maps_to_bad_response() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            result = [_problem_record(clock="not-a-clock")] if body["method"] == "problem.get" else [_trigger_record()]
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

        client = ZabbixClient.from_settings(make_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_active_problems()
        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"

    asyncio.run(run())


def test_active_problem_trigger_ids_are_unique_in_first_seen_order() -> None:
    async def run() -> None:
        seen_trigger_ids: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            if body["method"] == "problem.get":
                result = [
                    _problem_record(event_id="1", trigger_id="9002"),
                    _problem_record(event_id="2", trigger_id="9001"),
                    _problem_record(event_id="3", trigger_id="9002"),
                ]
            else:
                seen_trigger_ids.extend(body["params"]["triggerids"])
                result = [_trigger_record(trigger_id="9002"), _trigger_record(trigger_id="9001")]
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

        client = ZabbixClient.from_settings(make_settings(), transport=httpx.MockTransport(handler))
        problems = await client.list_active_problems()
        assert seen_trigger_ids == ["9002", "9001"]
        assert len(problems) == 3

    asyncio.run(run())


@pytest.mark.parametrize(
    "trigger_result",
    [
        [_trigger_record(trigger_id="9999")],
        [_trigger_record(), _trigger_record()],
        [_trigger_record(), _trigger_record(trigger_id="9999")],
        [{"hosts": []}],
        [{"triggerid": "   ", "hosts": []}],
        [{"triggerid": "9001", "hosts": {}}],
    ],
)
def test_invalid_trigger_result_maps_to_bad_response(trigger_result: list[dict]) -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            result = [_problem_record()] if body["method"] == "problem.get" else trigger_result
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

        client = ZabbixClient.from_settings(make_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_active_problems()
        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"

    asyncio.run(run())


def test_trigger_host_bound_rejects_more_than_32_hosts() -> None:
    async def run() -> None:
        hosts = [_trigger_host_record(host_id=str(index), technical_name=f"host-{index}") for index in range(33)]

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            result = [_problem_record()] if body["method"] == "problem.get" else [_trigger_record(hosts=hosts)]
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

        client = ZabbixClient.from_settings(make_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_active_problems()
        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"

    asyncio.run(run())


@pytest.mark.parametrize("field", ["hostid", "host", "name"])
def test_malformed_trigger_host_maps_to_bad_response(field: str) -> None:
    async def run() -> None:
        host = _trigger_host_record()
        host.pop(field)

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            result = [_problem_record()] if body["method"] == "problem.get" else [_trigger_record(hosts=[host])]
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

        client = ZabbixClient.from_settings(make_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_active_problems()
        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"

    asyncio.run(run())


@pytest.mark.parametrize("field", ["hostid", "host", "name"])
def test_blank_trigger_host_field_maps_to_bad_response(field: str) -> None:
    async def run() -> None:
        host = _trigger_host_record()
        host[field] = "   "

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            result = [_problem_record()] if body["method"] == "problem.get" else [_trigger_record(hosts=[host])]
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

        client = ZabbixClient.from_settings(make_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_active_problems()
        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"

    asyncio.run(run())


def test_duplicate_trigger_hosts_are_deduplicated_by_first_occurrence() -> None:
    async def run() -> None:
        hosts = [_trigger_host_record(name="First Name"), _trigger_host_record(name="Second Name")]

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            result = [_problem_record()] if body["method"] == "problem.get" else [_trigger_record(hosts=hosts)]
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

        client = ZabbixClient.from_settings(make_settings(), transport=httpx.MockTransport(handler))
        problems = await client.list_active_problems()
        assert len(problems[0].hosts) == 1
        assert problems[0].hosts[0].name == "First Name"

    asyncio.run(run())


def test_missing_trigger_mapping_keeps_problem_with_empty_hosts() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            result = [_problem_record()] if body["method"] == "problem.get" else []
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

        client = ZabbixClient.from_settings(make_settings(), transport=httpx.MockTransport(handler))
        problems = await client.list_active_problems()
        assert problems[0].event_id == "7001"
        assert problems[0].hosts == []

    asyncio.run(run())


def test_active_problem_malformed_json_maps_without_raw_body_leakage() -> None:
    async def run() -> None:
        marker = "active-problem-raw-marker"

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=marker)

        client = ZabbixClient.from_settings(make_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_active_problems()
        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"
        assert marker not in str(exc_info.value)
        assert marker not in repr(exc_info.value)

    asyncio.run(run())


def test_active_problem_http_auth_failure_does_not_leak_token() -> None:
    async def run() -> None:
        fake_token = "fake-active-problem-token-must-not-leak"

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"token": fake_token})

        client = ZabbixClient.from_settings(make_settings(zabbix_api_token=fake_token), transport=httpx.MockTransport(handler))
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_active_problems()
        assert exc_info.value.code == "SOURCE_AUTH_FAILED"
        assert fake_token not in str(exc_info.value)
        assert fake_token not in repr(exc_info.value)

    asyncio.run(run())


def test_active_problem_jsonrpc_auth_failure_does_not_leak_source_detail() -> None:
    async def run() -> None:
        marker = "Not authorized. active-problem-sensitive-marker"

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": body["id"], "error": {"code": -32602, "message": "Invalid params", "data": marker}},
            )

        client = ZabbixClient.from_settings(make_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_active_problems()
        assert exc_info.value.code == "SOURCE_AUTH_FAILED"
        assert marker not in str(exc_info.value)
        assert marker not in repr(exc_info.value)

    asyncio.run(run())


@pytest.mark.parametrize(("status", "expected_code"), [(429, "SOURCE_RATE_LIMITED"), (503, "SOURCE_UNAVAILABLE")])
def test_active_problem_transient_http_failure_uses_bounded_retries(monkeypatch, status: int, expected_code: str) -> None:
    async def run() -> None:
        attempts = 0
        delays: list[float] = []

        async def fake_sleep(delay: float) -> None:
            delays.append(delay)

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(status, json={"marker": "transient"})

        monkeypatch.setattr("app.core.http.asyncio.sleep", fake_sleep)
        client = ZabbixClient.from_settings(make_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_active_problems()
        assert attempts == 3
        assert delays == [0.25, 0.5]
        assert exc_info.value.code == expected_code
        assert exc_info.value.retryable is True

    asyncio.run(run())


def test_active_problem_connection_failure_uses_bounded_retries(monkeypatch) -> None:
    async def run() -> None:
        attempts = 0
        delays: list[float] = []

        async def fake_sleep(delay: float) -> None:
            delays.append(delay)

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            raise httpx.ConnectError("active problem connection failed", request=request)

        monkeypatch.setattr("app.core.http.asyncio.sleep", fake_sleep)
        client = ZabbixClient.from_settings(make_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_active_problems()
        assert attempts == 3
        assert delays == [0.25, 0.5]
        assert exc_info.value.code == "SOURCE_UNAVAILABLE"

    asyncio.run(run())


def test_trigger_get_mismatched_jsonrpc_id_maps_to_bad_response() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            if body["method"] == "problem.get":
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": [_problem_record()]})
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 999, "result": []})

        client = ZabbixClient.from_settings(make_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_active_problems()
        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"

    asyncio.run(run())


def test_trigger_get_http_auth_failure_maps_to_auth_failed() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            if body["method"] == "problem.get":
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": [_problem_record()]})
            return httpx.Response(401, json={"marker": "trigger-auth"})

        client = ZabbixClient.from_settings(make_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(IntegrationError) as exc_info:
            await client.list_active_problems()
        assert exc_info.value.code == "SOURCE_AUTH_FAILED"
        assert exc_info.value.retryable is False

    asyncio.run(run())


def test_zabbix_production_jsonrpc_method_literals_remain_read_only() -> None:
    source_path = Path(__file__).parents[2] / "app/integrations/zabbix/client.py"
    source = source_path.read_text()
    methods = set(re.findall(r'method="([a-z.]+)"', source))
    assert methods == {"host.get", "problem.get", "trigger.get"}
