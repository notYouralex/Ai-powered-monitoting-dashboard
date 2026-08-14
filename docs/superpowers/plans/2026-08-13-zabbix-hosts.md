# Zabbix Hosts Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first functional read-only Zabbix slice: authenticated JSON-RPC `host.get`, normalized host/interface availability data, and an authenticated `/api/dashboard/zabbix` response suitable for Grafana.

**Architecture:** Keep all Zabbix protocol semantics in `app/integrations/zabbix/`. Reuse shared settings, HTTP transport, authentication dependency, integration error handler, and health contract; do not add shared JSON-RPC abstractions, persistence, caching, Grafana provisioning, or Executive aggregation in this branch.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, httpx 0.28-compatible APIs, pytest, Zabbix JSON-RPC 2.0.

## Global Constraints

- Work only on `feature/zabbix-hosts`; never implement this feature directly on `main`.
- Zabbix access is strictly read-only; the client exposes `host.get` only and no generic arbitrary-method public API.
- Use the configured `ZABBIX_BASE_URL` as the JSON-RPC endpoint and `ZABBIX_API_TOKEN` through `Authorization: Bearer <token>`.
- Never put the API token in a JSON body, exception text, logs, public response, or normalized model.
- Use `Content-Type: application/json-rpc`, JSON-RPC version `2.0`, and verify the response request ID.
- Mark `host.get` retry-safe because it is read-only even though it uses HTTP POST.
- Retrieve only `hostid`, `host`, `name`, `status`, `maintenance_status`, and the required interface fields.
- Request at most 5001 hosts and reject a 5001-record result so the application never silently truncates above its 5000-host bound.
- Accept at most 32 interfaces per host.
- Normalize interface availability `0/1/2` to `unknown/available/unavailable` and interface type `1/2/3/4` to `agent/snmp/ipmi/jmx`; unknown future interface types become `unknown`.
- Do not add database migrations, shared contracts, Wazuh/Freshservice/Snipe-IT changes, Compose changes, Grafana files, or Executive aggregation.
- Follow strict RED → GREEN → REFACTOR TDD: no production behavior before a test has failed for the expected reason.
- Git commits are skipped until an explicit `user.name` and `user.email` are provided; do not invent an author identity.

---

## File Structure

- Create `app/integrations/zabbix/models.py` — bounded normalized Zabbix host/interface/dashboard Pydantic models.
- Create `app/integrations/zabbix/client.py` — read-only JSON-RPC `host.get` transport, normalization, bounds, and safe source-error mapping.
- Create `app/integrations/zabbix/service.py` — compose a current host snapshot into Grafana-facing summary and health metadata.
- Modify `app/integrations/zabbix/router.py` — authenticated `GET /api/dashboard/zabbix` endpoint and dependency factory.
- Create `tests/integrations/test_zabbix_client.py` — request shape, normalization, bounds, retry/error behavior, and mutation-surface regression tests.
- Create `tests/integrations/test_zabbix_service.py` — summary and health behavior.
- Create `tests/integrations/test_zabbix_router.py` — authentication, safe unconfigured response, normalized response, and mounted-route visibility.

---

### Task 1: Read-only `host.get` client and normalized host/interface models

**Files:**
- Create: `tests/integrations/test_zabbix_client.py`
- Create: `app/integrations/zabbix/models.py`
- Create: `app/integrations/zabbix/client.py`

**Interfaces:**
- Consumes: `Settings.integration_config_state("zabbix")`, `create_http_client(...)`, `request_with_retries(...)`, `IntegrationError`.
- Produces: `ZabbixClient.from_settings(settings, *, transport=None) -> ZabbixClient`, `ZabbixClient.list_hosts() -> list[ZabbixHost]`, `ZabbixHost`, `ZabbixHostInterface`.

- [ ] **Step 1: Write the first failing client tests**

Create `tests/integrations/test_zabbix_client.py` with a local `make_settings()` helper and tests proving unconfigured behavior plus exact successful request/normalization behavior:

```python
import asyncio
import json

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
                "hostid", "host", "name", "status", "maintenance_status"
            ]
            assert body["params"]["selectInterfaces"] == [
                "interfaceid", "type", "main", "useip", "ip", "dns", "available"
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
            make_settings(), transport=httpx.MockTransport(handler)
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
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python -m pytest tests/integrations/test_zabbix_client.py -q
```

Expected: collection fails because `app.integrations.zabbix.client` does not exist yet. If the environment cannot import project runtime dependencies, fix the local test environment before writing production code; do not count an environment/import-dependency failure as the required feature RED.

- [ ] **Step 3: Implement bounded normalized models**

Create `app/integrations/zabbix/models.py`:

```python
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts import IntegrationHealthSummary

ZabbixInterfaceType = Literal["agent", "snmp", "ipmi", "jmx", "unknown"]
ZabbixAvailability = Literal["available", "unavailable", "unknown"]


class ZabbixHostInterface(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interface_id: str = Field(min_length=1, max_length=64)
    type: ZabbixInterfaceType
    is_main: bool
    address: str | None = Field(default=None, max_length=512)
    availability: ZabbixAvailability


class ZabbixHost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_id: str = Field(min_length=1, max_length=64)
    technical_name: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=256)
    enabled: bool
    in_maintenance: bool
    interfaces: list[ZabbixHostInterface] = Field(default_factory=list, max_length=32)


class ZabbixDashboardSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hosts_total: int = Field(ge=0)
    hosts_enabled: int = Field(ge=0)
    hosts_disabled: int = Field(ge=0)
    hosts_in_maintenance: int = Field(ge=0)
    interfaces_available: int = Field(ge=0)
    interfaces_unavailable: int = Field(ge=0)
    interfaces_unknown: int = Field(ge=0)


class ZabbixDashboardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["zabbix"] = "zabbix"
    observed_at: datetime
    health: IntegrationHealthSummary
    summary: ZabbixDashboardSummary
    hosts: list[ZabbixHost] = Field(default_factory=list, max_length=5000)
    warnings: list[str] = Field(default_factory=list, max_length=20)
```

- [ ] **Step 4: Implement the minimal successful-path client**

Create `app/integrations/zabbix/client.py` with these required constants and methods:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import httpx
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.core.errors import IntegrationError, IntegrationErrorCode
from app.core.http import create_http_client, request_with_retries
from app.integrations.zabbix.models import (
    ZabbixAvailability,
    ZabbixHost,
    ZabbixHostInterface,
    ZabbixInterfaceType,
)

ZABBIX_HOST_LIMIT = 5000
ZABBIX_HOST_SENTINEL_LIMIT = ZABBIX_HOST_LIMIT + 1
ZABBIX_INTERFACE_LIMIT = 32
ZABBIX_REQUEST_ID = 1

_INTERFACE_TYPES: dict[str, ZabbixInterfaceType] = {
    "1": "agent",
    "2": "snmp",
    "3": "ipmi",
    "4": "jmx",
}
_AVAILABILITY: dict[str, ZabbixAvailability] = {
    "0": "unknown",
    "1": "available",
    "2": "unavailable",
}


class ZabbixClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_token: SecretStr,
        verify_tls: bool,
        ca_bundle: Path | None,
        timeout_seconds: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._api_token = api_token
        self._verify_tls = verify_tls
        self._ca_bundle = ca_bundle
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @classmethod
    def from_settings(cls, settings: Settings, *, transport=None) -> "ZabbixClient":
        base_url = settings.zabbix_base_url
        api_token = settings.zabbix_api_token
        if (
            settings.integration_config_state("zabbix") != "configured"
            or base_url is None
            or api_token is None
        ):
            raise IntegrationError(
                source="zabbix", code="SOURCE_NOT_CONFIGURED", retryable=False
            )
        return cls(
            base_url=str(base_url),
            api_token=api_token,
            verify_tls=settings.zabbix_verify_tls,
            ca_bundle=settings.zabbix_ca_bundle,
            timeout_seconds=settings.zabbix_timeout_seconds,
            transport=transport,
        )

    async def list_hosts(self) -> list[ZabbixHost]:
        async with create_http_client(
            timeout_seconds=self._timeout_seconds,
            verify_tls=self._verify_tls,
            ca_bundle=self._ca_bundle,
            transport=self._transport,
        ) as client:
            response = await request_with_retries(
                client,
                "POST",
                self._base_url,
                retry_safe=True,
                headers={
                    "Authorization": f"Bearer {self._api_token.get_secret_value()}",
                    "Content-Type": "application/json-rpc",
                },
                json={
                    "jsonrpc": "2.0",
                    "method": "host.get",
                    "params": {
                        "output": [
                            "hostid", "host", "name", "status", "maintenance_status"
                        ],
                        "selectInterfaces": [
                            "interfaceid", "type", "main", "useip", "ip", "dns", "available"
                        ],
                        "limit": ZABBIX_HOST_SENTINEL_LIMIT,
                        "sortfield": "hostid",
                    },
                    "id": ZABBIX_REQUEST_ID,
                },
            )
        payload = response.json()
        result = payload["result"]
        return [self._normalize_host(item) for item in result]

    @staticmethod
    def _normalize_host(item: Any) -> ZabbixHost:
        interfaces = item.get("interfaces", [])
        return ZabbixHost(
            host_id=_required_string(item.get("hostid")),
            technical_name=_required_string(item.get("host")),
            name=_required_string(item.get("name")),
            enabled=_binary_bool(item.get("status"), true_value="0"),
            in_maintenance=_binary_bool(item.get("maintenance_status"), true_value="1"),
            interfaces=[ZabbixClient._normalize_interface(value) for value in interfaces],
        )

    @staticmethod
    def _normalize_interface(item: Any) -> ZabbixHostInterface:
        use_ip = _binary_bool(item.get("useip"), true_value="1")
        address = item.get("ip") if use_ip else item.get("dns")
        return ZabbixHostInterface(
            interface_id=_required_string(item.get("interfaceid")),
            type=_INTERFACE_TYPES.get(str(item.get("type")), "unknown"),
            is_main=_binary_bool(item.get("main"), true_value="1"),
            address=_optional_string(address),
            availability=_AVAILABILITY.get(str(item.get("available")), "unknown"),
        )
```

Also implement `_required_string`, `_optional_string`, and `_binary_bool`; `_binary_bool` must accept only source values `"0"` and `"1"` and raise `ValueError` for anything else.

- [ ] **Step 5: Run the client tests and verify GREEN**

Run:

```bash
python -m pytest tests/integrations/test_zabbix_client.py -q
```

Expected: the two initial tests pass.

- [ ] **Step 6: Refactor without adding behavior**

Remove unused imports, keep helper names source-local, and rerun the focused tests. Do not add error/retry branches until Task 2 has failing tests for them.

---

### Task 2: Safe JSON-RPC validation, error mapping, retries, and payload bounds

**Files:**
- Modify: `tests/integrations/test_zabbix_client.py`
- Modify: `app/integrations/zabbix/client.py`

**Interfaces:**
- Consumes: Task 1 `ZabbixClient.list_hosts()`.
- Produces: safe mapping to existing `IntegrationErrorCode` values and strict 5000-host/32-interface bounds.

- [ ] **Step 1: Add failing tests for JSON-RPC and HTTP failure behavior**

Add separate tests covering:

```python
# malformed body -> SOURCE_BAD_RESPONSE
return httpx.Response(200, text="raw-zabbix-marker")

# mismatched request id -> SOURCE_BAD_RESPONSE
return httpx.Response(200, json={"jsonrpc": "2.0", "id": 999, "result": []})

# wrong jsonrpc version -> SOURCE_BAD_RESPONSE
return httpx.Response(200, json={"jsonrpc": "1.0", "id": 1, "result": []})

# HTTP auth -> SOURCE_AUTH_FAILED
return httpx.Response(401, json={"marker": fake_token})

# JSON-RPC auth classification -> SOURCE_AUTH_FAILED without source text leakage
return httpx.Response(
    200,
    json={
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": -32602,
            "message": "Invalid params.",
            "data": "Not authorized.",
        },
    },
)

# non-auth JSON-RPC error -> SOURCE_BAD_RESPONSE
# 429 after shared retries -> SOURCE_RATE_LIMITED and exactly 3 attempts
# 503 after shared retries -> SOURCE_UNAVAILABLE and exactly 3 attempts
# ConnectError after shared retries -> SOURCE_UNAVAILABLE and exactly 3 attempts
```

For every error test, assert raw body markers, API token values, and JSON-RPC error `data` do not appear in `str(exc)` or `repr(exc)`.

- [ ] **Step 2: Add failing tests for bounds and malformed source records**

Add tests proving:

```python
# 5001 host records -> SOURCE_BAD_RESPONSE
# 33 interfaces on one host -> SOURCE_BAD_RESPONSE
# invalid host status "2" -> SOURCE_BAD_RESPONSE
# missing required hostid/name/host -> SOURCE_BAD_RESPONSE
# empty result [] -> []
# unknown future interface type "9" -> type == "unknown"
# unknown availability value "9" -> availability == "unknown"
```

Also add a source-surface regression test:

```python
def test_public_client_exposes_no_mutation_methods() -> None:
    public = {name for name in dir(ZabbixClient) if not name.startswith("_")}
    assert "create" not in public
    assert "update" not in public
    assert "delete" not in public
    assert "request" not in public
    assert "call" not in public
    assert "list_hosts" in public
```

- [ ] **Step 3: Run the new tests and verify RED**

Run:

```bash
python -m pytest tests/integrations/test_zabbix_client.py -q
```

Expected: the new error/bounds tests fail because Task 1 only implemented the successful path.

- [ ] **Step 4: Implement safe response validation and status mapping**

Update `list_hosts()` to catch `httpx.RequestError`, validate HTTP status, parse only an object JSON payload, validate `jsonrpc == "2.0"`, validate `id == ZABBIX_REQUEST_ID`, reject simultaneous/missing `result` and `error`, and normalize records inside a `try` block that maps `(KeyError, TypeError, ValueError, ValidationError)` to `SOURCE_BAD_RESPONSE`.

Add source-local helpers with these behaviors:

```python
def _raise_for_status(self, response: httpx.Response) -> None:
    status = response.status_code
    if 200 <= status < 300:
        return
    if status in {401, 403}:
        raise self._source_error("SOURCE_AUTH_FAILED", retryable=False)
    if status == 429:
        raise self._source_error("SOURCE_RATE_LIMITED", retryable=True)
    if status >= 500:
        raise self._source_error("SOURCE_UNAVAILABLE", retryable=True)
    raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)


def _parse_payload(self, response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False) from exc
    if not isinstance(payload, dict):
        raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)
    return payload


@staticmethod
def _source_error(code: IntegrationErrorCode, *, retryable: bool) -> IntegrationError:
    return IntegrationError(source="zabbix", code=code, retryable=retryable)
```

JSON-RPC error classification must inspect only `error.get("data")` when it is a string and classify `"not authorized"` case-insensitively as authentication failure; never propagate that string.

Enforce:

```python
if len(result) > ZABBIX_HOST_LIMIT:
    raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)
if len(interfaces) > ZABBIX_INTERFACE_LIMIT:
    raise ValueError("too many interfaces")
```

- [ ] **Step 5: Run the full client tests and verify GREEN**

Run:

```bash
python -m pytest tests/integrations/test_zabbix_client.py -q
```

Expected: all Zabbix client tests pass with bounded retry counts and no leaked source text/token values.

---

### Task 3: Grafana-facing Zabbix dashboard service

**Files:**
- Create: `tests/integrations/test_zabbix_service.py`
- Create: `app/integrations/zabbix/service.py`

**Interfaces:**
- Consumes: `ZabbixClient.list_hosts() -> list[ZabbixHost]`.
- Produces: `ZabbixDashboardService.get_dashboard() -> ZabbixDashboardResponse`.

- [ ] **Step 1: Write failing service tests**

Create a fake client returning three hosts: one enabled/available, one disabled/unavailable, and one enabled/in-maintenance with unknown interface availability. Assert:

```python
response.source == "zabbix"
response.health.source == "zabbix"
response.health.status == "healthy"
response.health.is_stale is False
response.summary.hosts_total == 3
response.summary.hosts_enabled == 2
response.summary.hosts_disabled == 1
response.summary.hosts_in_maintenance == 1
response.summary.interfaces_available == 1
response.summary.interfaces_unavailable == 1
response.summary.interfaces_unknown == 1
response.hosts == hosts
```

Add a second test proving an empty host list returns all zero summary counts and healthy status.

- [ ] **Step 2: Run service tests and verify RED**

Run:

```bash
python -m pytest tests/integrations/test_zabbix_service.py -q
```

Expected: collection fails because `app.integrations.zabbix.service` does not exist.

- [ ] **Step 3: Implement `ZabbixDashboardService`**

Create `app/integrations/zabbix/service.py`:

```python
from datetime import datetime, timezone
from time import perf_counter

from app.contracts import IntegrationHealthSummary
from app.integrations.zabbix.client import ZabbixClient
from app.integrations.zabbix.models import (
    ZabbixDashboardResponse,
    ZabbixDashboardSummary,
    ZabbixHost,
)


class ZabbixDashboardService:
    def __init__(self, *, client: ZabbixClient) -> None:
        self._client = client

    async def get_dashboard(self) -> ZabbixDashboardResponse:
        started = perf_counter()
        hosts = await self._client.list_hosts()
        observed_at = datetime.now(timezone.utc)
        response_time_ms = max(0, int((perf_counter() - started) * 1000))
        return ZabbixDashboardResponse(
            observed_at=observed_at,
            health=IntegrationHealthSummary(
                source="zabbix",
                status="healthy",
                observed_at=observed_at,
                last_success_at=observed_at,
                response_time_ms=response_time_ms,
                is_stale=False,
                warnings=[],
            ),
            summary=_build_summary(hosts),
            hosts=hosts,
        )
```

Implement `_build_summary(hosts)` with direct counts only; do not add problems, trends, persistence, or caching.

- [ ] **Step 4: Run service tests and verify GREEN**

Run:

```bash
python -m pytest tests/integrations/test_zabbix_service.py -q
```

Expected: all service tests pass.

---

### Task 4: Authenticated `/api/dashboard/zabbix` route

**Files:**
- Create: `tests/integrations/test_zabbix_router.py`
- Modify: `app/integrations/zabbix/router.py`

**Interfaces:**
- Consumes: existing `get_current_user`, `get_settings`, `ZabbixClient.from_settings()`, and `ZabbixDashboardService`.
- Produces: authenticated `GET /api/dashboard/zabbix` returning `ZabbixDashboardResponse`.

- [ ] **Step 1: Write failing router tests**

Follow the existing Wazuh router-test fixture pattern and create tests for:

```python
# unauthenticated request -> 401 {"detail": "Not authenticated"}
# authenticated but unconfigured -> 503 SOURCE_NOT_CONFIGURED with source=zabbix and request_id
# dependency override returns fake normalized dashboard -> 200, source=zabbix, expected host counts
# create_app().openapi()["paths"] contains "/api/dashboard/zabbix"
```

The fake service interface is:

```python
class FakeDashboardService:
    async def get_dashboard(self) -> ZabbixDashboardResponse:
        ...
```

- [ ] **Step 2: Run router tests and verify RED**

Run:

```bash
python -m pytest tests/integrations/test_zabbix_router.py -q
```

Expected: route tests fail because the current Zabbix router is empty.

- [ ] **Step 3: Implement the router and dependency factory**

Replace `app/integrations/zabbix/router.py` with:

```python
from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.integrations.zabbix.client import ZabbixClient
from app.integrations.zabbix.models import ZabbixDashboardResponse
from app.integrations.zabbix.service import ZabbixDashboardService

router = APIRouter(
    prefix="/api/dashboard/zabbix",
    tags=["dashboard", "zabbix"],
    dependencies=[Depends(get_current_user)],
)


def get_zabbix_dashboard_service(
    settings: Settings = Depends(get_settings),
) -> ZabbixDashboardService:
    return ZabbixDashboardService(client=ZabbixClient.from_settings(settings))


@router.get("", response_model=ZabbixDashboardResponse)
async def get_zabbix_dashboard(
    service: ZabbixDashboardService = Depends(get_zabbix_dashboard_service),
) -> ZabbixDashboardResponse:
    return await service.get_dashboard()
```

- [ ] **Step 4: Run router tests and verify GREEN**

Run:

```bash
python -m pytest tests/integrations/test_zabbix_router.py -q
```

Expected: all Zabbix router tests pass.

---

### Task 5: Feature-level validation and diff review

**Files:**
- Review all task-owned files only; no new production behavior.

- [ ] **Step 1: Run all focused Zabbix tests**

```bash
python -m pytest \
  tests/integrations/test_zabbix_client.py \
  tests/integrations/test_zabbix_service.py \
  tests/integrations/test_zabbix_router.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the full available suite**

```bash
python -m pytest -q
```

Expected: PASS. If environment dependencies make the full suite unavailable, record the exact environment blocker and still run every available focused/static check; do not claim the suite passed.

- [ ] **Step 3: Run syntax and whitespace validation**

```bash
python3 -m compileall -q app tests
git diff --check
git diff --cached --check
```

Expected: all exit 0.

- [ ] **Step 4: Verify the Zabbix production surface is read-only**

```bash
grep -RInE 'host\.(create|update|delete|massupdate)|item\.(create|update|delete)|trigger\.(create|update|delete)|hostinterface\.(create|update|delete|mass)' app/integrations/zabbix && exit 1 || true
```

Expected: no matches.

Verify the only source JSON-RPC method literal in production Zabbix code is `host.get`.

- [ ] **Step 5: Scan task-owned changes for credential leakage**

Search changed files for private-key headers, obvious token formats, `Authorization` logging/printing, and raw-response logging. Test fixtures may contain clearly fake token strings; production files must contain no real secret literals.

- [ ] **Step 6: Review final diff and Git status**

Confirm changes are limited to the approved design/plan plus Zabbix-owned implementation/tests. Do not stage unrelated files. Because Git author identity is not configured, leave the implementation uncommitted unless the user explicitly provides `user.name` and `user.email`.
