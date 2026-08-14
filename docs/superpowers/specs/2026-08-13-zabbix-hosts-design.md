# Zabbix Hosts Integration Design

**Date:** 2026-08-13
**Branch:** `feature/zabbix-hosts`
**Owner boundary:** Intern B / `app/integrations/zabbix/`

## 1. Goal

Implement the first functional Zabbix slice: a read-only JSON-RPC client that retrieves hosts and host-interface availability, normalizes the source response inside the Zabbix package, and exposes an authenticated Grafana-facing FastAPI endpoint at `/api/dashboard/zabbix`.

This slice establishes the Zabbix adapter boundary needed before adding active problems, CPU/memory/disk pressure, trends, top affected hosts, Grafana provisioning, or Executive aggregation.

## 2. Existing Constraints

The repository already provides:

- optional `ZABBIX_BASE_URL`, `ZABBIX_API_TOKEN`, `ZABBIX_VERIFY_TLS`, `ZABBIX_CA_BUNDLE`, and `ZABBIX_TIMEOUT_SECONDS` settings;
- production TLS enforcement for configured integrations;
- bounded shared `httpx` transport and opt-in retry behavior;
- source-neutral `IntegrationError` handling;
- an empty Zabbix router already mounted through the shared integration router;
- authentication dependencies for dashboard endpoints.

Repository security rules require Zabbix access to remain read-only. No configuration writes, remote commands, service restarts, or other source mutations are permitted.

The repository does not declare a target Zabbix server version. The implementation will follow the current official Zabbix JSON-RPC behavior: requests use HTTP POST to the configured `api_jsonrpc.php` endpoint, API-token authorization is supplied through the `Authorization: Bearer` header, and read requests explicitly request only required object properties. Deployment must confirm the target Zabbix version supports that authorization form; compatibility with older API-token placement is outside this slice.

## 3. Approaches Considered

### A. Focused host client and normalized endpoint — selected

Add only the Zabbix-specific client, normalized host/interface models, small dashboard service, endpoint, and owned tests. Reuse the existing shared transport and error types.

**Why selected:** smallest safe vertical slice, follows repository ownership boundaries, produces Grafana-ready data, and leaves future problem/metric work additive.

### B. Generic shared JSON-RPC framework

Add reusable JSON-RPC request/response machinery in `app/core/` and make Zabbix consume it.

**Rejected for now:** the repository explicitly keeps source semantics inside source packages. A generic framework would create an unnecessary shared-contract change before another integration needs it.

### C. Full Zabbix dashboard in one branch

Implement hosts, problems, CPU/memory/disk metrics, trends, caching, and Grafana panels together.

**Rejected for now:** too broad for one feature branch and would make failures harder to isolate. The repository roadmap favors focused source branches.

## 4. Architecture

### `app/integrations/zabbix/client.py`

`ZabbixClient` owns Zabbix JSON-RPC transport semantics.

Public interface:

```python
class ZabbixClient:
    @classmethod
    def from_settings(cls, settings: Settings, *, transport=None) -> "ZabbixClient": ...

    async def list_hosts(self) -> list[ZabbixHost]: ...
```

`from_settings()` raises `IntegrationError(source="zabbix", code="SOURCE_NOT_CONFIGURED")` unless both the base URL and API token are present.

`list_hosts()` performs only `host.get`. The public client will not expose a generic arbitrary-method API, which prevents consumers from casually calling Zabbix mutation methods.

The JSON-RPC request uses:

- HTTP method `POST`;
- the configured `ZABBIX_BASE_URL` exactly as supplied;
- `Content-Type: application/json-rpc`;
- `Authorization: Bearer <token>`;
- JSON-RPC version `2.0`;
- a request ID that is checked against the response;
- `retry_safe=True` because `host.get` is read-only even though the HTTP method is POST.

The `host.get` request explicitly asks for only the fields needed by this slice and uses `limit=5001`. The client accepts at most 5000 hosts; receiving the sentinel 5001st record is treated as `SOURCE_BAD_RESPONSE` so the dashboard never silently truncates a larger environment.

```text
hostid
host
name
status
maintenance_status
interfaces.interfaceid
interfaces.type
interfaces.main
interfaces.useip
interfaces.ip
interfaces.dns
interfaces.available
```

Each normalized host accepts at most 32 interfaces. More than 32 interfaces on one host is treated as `SOURCE_BAD_RESPONSE`. These bounds are intentionally far above the approved 100–200 device scale while keeping the Grafana-facing payload controlled.

The API token must never appear in the JSON body, model representations, logs, raised error text, or public responses.

### `app/integrations/zabbix/models.py`

Source-specific response shapes stop here and are converted to bounded normalized models.

Planned models:

```text
ZabbixInterfaceType = agent | snmp | ipmi | jmx | unknown
ZabbixAvailability = available | unavailable | unknown

ZabbixHostInterface
- interface_id
- type
- is_main
- address
- availability

ZabbixHost
- host_id
- technical_name
- name
- enabled
- in_maintenance
- interfaces[]

ZabbixDashboardSummary
- hosts_total
- hosts_enabled
- hosts_disabled
- hosts_in_maintenance
- interfaces_available
- interfaces_unavailable
- interfaces_unknown

ZabbixDashboardResponse
- source = zabbix
- observed_at
- health
- summary
- hosts[]
- warnings[]
```

Interface availability is normalized from the Zabbix values `0/1/2` to `unknown/available/unavailable`. Interface type is normalized from the documented numeric values to `agent/snmp/ipmi/jmx`; unknown future values become `unknown` rather than leaking source-specific integers to consumers.

The host `status` field is represented as `enabled: bool`; `maintenance_status` becomes `in_maintenance: bool`. Structurally invalid required host data maps to `SOURCE_BAD_RESPONSE`.

The interface `address` uses the interface IP when `useip=1`; otherwise it uses DNS. Empty values normalize to `None`.

### `app/integrations/zabbix/service.py`

`ZabbixDashboardService` composes the normalized host snapshot into a Grafana-facing response.

Public interface:

```python
class ZabbixDashboardService:
    async def get_dashboard(self) -> ZabbixDashboardResponse: ...
```

The service records `observed_at`, response time, and healthy integration state after a successful client call. It calculates only the host/interface counts listed above.

No database persistence or shared cache is added in this slice. The approved architecture calls for a short Zabbix cache later; that belongs with the later dashboard-enrichment/caching work rather than the first host client.

### `app/integrations/zabbix/router.py`

The existing empty router becomes:

```text
GET /api/dashboard/zabbix
```

The endpoint:

- requires the existing local authentication dependency;
- builds `ZabbixClient` from settings;
- returns `ZabbixDashboardResponse`;
- accepts no time-range parameters in this host-only slice because host/interface availability is a current snapshot.

Later Zabbix problem/trend work may add bounded time-range parameters without changing the host models.

## 5. Error Handling

The client maps failures to the existing safe source-neutral errors:

- missing configuration → `SOURCE_NOT_CONFIGURED`, non-retryable;
- HTTP 401/403 → `SOURCE_AUTH_FAILED`, non-retryable;
- a JSON-RPC error whose `data` string contains `not authorized` case-insensitively → `SOURCE_AUTH_FAILED`, non-retryable; the source text is used only for classification and is never propagated;
- connection/timeout or HTTP 5xx → `SOURCE_UNAVAILABLE`, retryable;
- HTTP 429 → `SOURCE_RATE_LIMITED`, retryable;
- malformed JSON, mismatched JSON-RPC ID/version, unexpected result shape, invalid host records, or non-auth JSON-RPC errors → `SOURCE_BAD_RESPONSE`, non-retryable.

`host.get` is marked retry-safe, so the existing shared helper may perform at most three total attempts for its already-approved transient cases.

Raw Zabbix error `message`/`data`, response bodies, token values, and authorization headers must not be copied into public errors.

## 6. Testing Strategy

All implementation tests are written before production code.

### Client tests

Cover:

- unconfigured settings;
- exact read-only `host.get` request shape;
- Bearer token header and absence of token from JSON body;
- normalized hosts and interfaces;
- enabled/disabled and maintenance state;
- interface availability and interface-type normalization;
- IP-versus-DNS address selection;
- empty host list;
- malformed JSON and malformed JSON-RPC envelopes;
- request-ID mismatch;
- HTTP authentication failure;
- JSON-RPC authorization failure without token/error leakage;
- bounded retry behavior for 429 and transient connectivity failures;
- server failure mapping;
- invalid host record mapping;
- no mutation method requests.

### Service tests

Cover summary counts, healthy integration metadata, empty results, and stable normalized output.

### Router tests

Cover authentication requirement, safe unconfigured response, successful normalized response, and route visibility through the already-mounted Zabbix router.

### Validation

Before completion:

- run focused Zabbix tests;
- run the full available pytest suite;
- run Python syntax compilation;
- run `git diff --check`;
- scan the changed Zabbix integration for mutation method names and secret leakage;
- review the final diff for unrelated/shared-file changes.

## 7. Files in Scope

Implementation phase should normally create or modify only:

```text
app/integrations/zabbix/client.py
app/integrations/zabbix/models.py
app/integrations/zabbix/service.py
app/integrations/zabbix/router.py
tests/integrations/test_zabbix_client.py
tests/integrations/test_zabbix_service.py
tests/integrations/test_zabbix_router.py
```

The design file itself is also part of this branch.

No migration, database model, shared contract, Wazuh/Freshservice code, Snipe-IT code, Compose behavior, Grafana provisioning, or Executive aggregation change is required for this slice.

## 8. Definition of Done

This feature is done when an authenticated caller can request `/api/dashboard/zabbix` and receive a bounded normalized host/interface availability snapshot from a configured Zabbix API token, with safe failure behavior and no source mutation capability.

The next Zabbix feature after this slice is active-problem retrieval and normalization, followed by resource-pressure metrics/trends, caching, and the Grafana Zabbix infrastructure dashboard.
