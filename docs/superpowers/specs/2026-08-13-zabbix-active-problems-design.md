# Zabbix Active Problems Integration Design

**Date:** 2026-08-13
**Branch:** `feature/zabbix-hosts`
**Owner boundary:** Intern B / `app/integrations/zabbix/`
**Commit policy:** Keep this spec and its implementation uncommitted until the user requests the single combined Zabbix commit.

## 1. Goal

Extend the existing read-only Zabbix dashboard slice with active problem retrieval and normalization. The authenticated `GET /api/dashboard/zabbix` response will continue to expose current host/interface availability and will additionally expose unresolved trigger problems, severity counts, acknowledgement/suppression state, and affected host identities.

This task implements the second Zabbix capability required by the repository architecture. The project design lists the Zabbix infrastructure dashboard sequence as host availability, active problems, CPU/memory/disk pressure, trend, top affected hosts, and AI infrastructure summary. Resource metrics, trends, caching, Grafana provisioning, and Executive aggregation remain outside this slice.

## 2. Source of Requirements

Repository requirements come from the existing platform and Zabbix Markdown files:

- `docs/superpowers/specs/2026-08-06-ai-powered-monitoring-platform-design.md` requires active Zabbix problems as part of the infrastructure dashboard.
- `docs/superpowers/specs/2026-08-13-zabbix-hosts-design.md` explicitly identifies active-problem retrieval and normalization as the next Zabbix feature after host availability.
- `AGENTS.md` requires all source integrations to remain read-only and source-specific API formats to stay within the owning integration package.

The repository Markdown does not define the exact Zabbix API calls. Those mechanics are therefore derived from the current official Zabbix 7.4 API documentation:

- `problem.get` retrieves problems and supports unresolved-only retrieval with `recent=false`.
- Trigger problems are the default problem source/object type.
- A problem object's `objectid` is the related trigger ID for trigger-generated problems.
- `trigger.get` accepts `triggerids` and supports `selectHosts`, which provides the host objects associated with each trigger.
- Problem objects expose `eventid`, `objectid`, `clock`, `name`, `acknowledged`, `severity`, and `suppressed`.

## 3. Selected Approach

Use two read-only Zabbix calls:

1. `problem.get` retrieves a bounded list of unresolved trigger problems.
2. `trigger.get` resolves the unique trigger IDs returned by `problem.get` into affected hosts using `selectHosts`.

This preserves event-level problem information from `problem.get` while providing reliable host IDs/names from the trigger relationship.

### Alternatives rejected

**Only `problem.get`:** simpler, but does not directly return the trigger's host collection. The dashboard would lose reliable affected-host identities.

**Only `trigger.get`:** can expose problem-state triggers and host information, but does not provide the problem event's acknowledgement/suppression state needed by the dashboard.

**`event.get` instead of `problem.get`:** unnecessary for this slice. The repository calls for active problems, and `problem.get` is the Zabbix API specifically intended for unresolved/recent problem retrieval. Historical resolved-event work belongs with later trends/history requirements.

## 4. Read-Only Client Interface

`app/integrations/zabbix/client.py` remains the only owner of Zabbix JSON-RPC details.

The public client interface becomes:

```python
class ZabbixClient:
    async def list_hosts(self) -> list[ZabbixHost]: ...
    async def list_active_problems(self) -> list[ZabbixProblem]: ...
```

No public generic `request`, `call`, `create`, `update`, `delete`, or arbitrary-method API will be exposed.

A private JSON-RPC helper may be introduced to remove duplicate transport/status/envelope validation across `host.get`, `problem.get`, and `trigger.get`. If introduced, it remains private and is used only by explicitly coded read methods.

The only allowed production JSON-RPC method literals after this slice are:

```text
host.get
problem.get
trigger.get
```

No `event.acknowledge` or other mutation method may be implemented.

## 5. `problem.get` Request

`list_active_problems()` first issues an authenticated retry-safe HTTP POST to the configured Zabbix JSON-RPC endpoint.

Request requirements:

```text
method: problem.get
recent: false
source: 0
object: 0
sortfield: eventid
sortorder: DESC
limit: 1001
output:
  eventid
  objectid
  clock
  name
  acknowledged
  severity
  suppressed
```

`source=0` and `object=0` make the trigger-problem boundary explicit even though trigger problems are the documented defaults.

The client accepts at most 1000 active problems. The request asks for 1001 records as a sentinel. If Zabbix returns 1001 records, the client maps the response to `SOURCE_BAD_RESPONSE` rather than silently truncating the dashboard. This bound is intentionally well above the currently approved environment scale while preventing an unbounded Grafana-facing response.

No problem acknowledgement history, suppression detail, tags, operational data, or raw source error text is requested in this slice because the normalized response only needs current state.

## 6. `trigger.get` Host Resolution

If `problem.get` returns no problems, `list_active_problems()` returns `[]` without issuing `trigger.get`.

Otherwise, the client extracts unique problem `objectid` values and sends one bounded read-only `trigger.get` request:

```text
method: trigger.get
triggerids: <unique problem objectids>
output:
  triggerid
selectHosts:
  hostid
  host
  name
```

The trigger lookup accepts only the trigger IDs obtained from the already-bounded problem result. The response may contain at most the number of requested unique trigger IDs; duplicates, unknown trigger IDs, malformed trigger IDs, or a result larger than the requested set are treated as `SOURCE_BAD_RESPONSE`.

Each trigger accepts at most 32 associated hosts. More than 32 returned hosts for one trigger is treated as `SOURCE_BAD_RESPONSE`.

Zabbix documents that `problem.get` may temporarily return problems for deleted entities before housekeeping removes them. Therefore a problem whose trigger ID is absent from a valid `trigger.get` response is not fatal. It is returned with an empty `hosts` list, allowing the active problem to remain visible instead of breaking the entire dashboard.

## 7. Normalized Models

Extend `app/integrations/zabbix/models.py` with source-neutral Zabbix-facing models.

```text
ZabbixProblemSeverity =
  not_classified |
  information |
  warning |
  average |
  high |
  disaster |
  unknown

ZabbixProblemHost
- host_id: str
- technical_name: str
- name: str

ZabbixProblem
- event_id: str
- trigger_id: str
- name: str
- severity: ZabbixProblemSeverity
- started_at: datetime
- acknowledged: bool
- suppressed: bool
- hosts: list[ZabbixProblemHost]
```

Severity normalization follows documented Zabbix values:

```text
0 -> not_classified
1 -> information
2 -> warning
3 -> average
4 -> high
5 -> disaster
other future value -> unknown
```

The `clock` Unix timestamp becomes a timezone-aware UTC `datetime`.

`acknowledged` and `suppressed` must accept only source values `0` or `1`; other values are malformed source data and map to `SOURCE_BAD_RESPONSE`.

Host objects require non-empty `hostid`, `host`, and `name`. Duplicate host IDs in one trigger result are deduplicated deterministically by first occurrence.

## 8. Dashboard Response Changes

Extend `ZabbixDashboardSummary` with:

```text
problems_total
problems_not_classified
problems_information
problems_warning
problems_average
problems_high
problems_disaster
problems_unknown
problems_unacknowledged
problems_suppressed
```

Extend `ZabbixDashboardResponse` with:

```text
active_problems: list[ZabbixProblem]
```

The list is bounded to 1000 problems.

The existing host/interface fields remain unchanged so this slice is additive for Grafana consumers.

## 9. Dashboard Service Behavior

`ZabbixDashboardService.get_dashboard()` retrieves hosts and active problems concurrently:

```python
hosts, active_problems = await asyncio.gather(
    self._client.list_hosts(),
    self._client.list_active_problems(),
)
```

A successful response represents one current dashboard observation and includes both host and problem summaries.

Summary calculations:

- `problems_total` = number of normalized active problems;
- each severity field = count for that normalized severity;
- `problems_unacknowledged` = number with `acknowledged is False`;
- `problems_suppressed` = number with `suppressed is True`.

If a normalized problem has no resolved hosts, the dashboard remains healthy but includes one bounded warning summarizing the number of active problems whose trigger-to-host relationship could not be resolved, for example:

```text
1 active Zabbix problem could not be mapped to a current host.
```

or

```text
3 active Zabbix problems could not be mapped to a current host.
```

Do not include event IDs, trigger IDs, source error text, credentials, or raw responses in warnings.

If either the host query or the active-problem query raises an `IntegrationError`, the whole source request fails using the existing safe error handler. Partial-source caching/staleness is intentionally deferred to the later caching slice.

## 10. Error Handling

Both `problem.get` and `trigger.get` reuse the same safe transport/envelope rules already established for `host.get`:

- missing configuration -> `SOURCE_NOT_CONFIGURED`, non-retryable;
- HTTP 401/403 -> `SOURCE_AUTH_FAILED`, non-retryable;
- recognized JSON-RPC authorization error -> `SOURCE_AUTH_FAILED`, non-retryable;
- HTTP 429 -> `SOURCE_RATE_LIMITED`, retryable after shared bounded retries;
- connection error/timeout or HTTP 5xx -> `SOURCE_UNAVAILABLE`, retryable after shared bounded retries;
- malformed JSON, wrong JSON-RPC version, mismatched request ID, unexpected result shape, invalid problem/trigger/host records, or non-auth JSON-RPC error -> `SOURCE_BAD_RESPONSE`, non-retryable.

Both calls are marked `retry_safe=True` because they are read-only even though JSON-RPC uses HTTP POST.

Raw Zabbix response bodies, API token values, authorization headers, JSON-RPC `error.message`, and JSON-RPC `error.data` are never propagated to application responses or logs.

## 11. Testing Strategy

Implementation follows strict RED -> GREEN -> REFACTOR TDD.

### Client tests

Add tests proving:

- exact `problem.get` request shape and Bearer authentication;
- only unresolved trigger problems are requested (`recent=false`, `source=0`, `object=0`);
- 1001-problem sentinel rejection;
- empty problem list skips `trigger.get`;
- unique trigger IDs are passed to `trigger.get`;
- exact `trigger.get` request includes `selectHosts=["hostid", "host", "name"]`;
- event/trigger/problem fields normalize correctly;
- severity mapping for all six documented values and future unknown values;
- Unix `clock` becomes UTC datetime;
- acknowledged/suppressed `0/1` normalize to booleans and invalid values are rejected;
- multi-host triggers normalize all hosts;
- duplicate hosts are deduplicated;
- more than 32 hosts on one trigger is rejected;
- extra/unrequested/duplicate trigger records are rejected;
- a missing trigger mapping produces `hosts=[]` without failing;
- malformed problem/trigger/host records map to `SOURCE_BAD_RESPONSE`;
- HTTP/JSON-RPC auth, rate limit, transient server, connection, malformed body, and request-ID errors preserve safe mappings;
- API token and raw source markers never leak;
- the public client still exposes no generic or mutation methods;
- the only production Zabbix JSON-RPC methods are `host.get`, `problem.get`, and `trigger.get`.

### Service tests

Extend service tests for:

- concurrent host/problem retrieval behavior;
- all severity summary counts;
- unacknowledged and suppressed counts;
- zero-problem snapshot;
- unmapped-host warning singular/plural behavior;
- `active_problems` returned unchanged from normalized client output.

### Router tests

The route path and authentication behavior do not change. Extend the normalized-response router fixture to prove `/api/dashboard/zabbix` serializes the new summary fields and `active_problems` list.

## 12. Files in Scope

This slice should modify only the existing uncommitted Zabbix feature files plus its owned tests and design/plan documentation:

```text
app/integrations/zabbix/client.py
app/integrations/zabbix/models.py
app/integrations/zabbix/service.py
tests/integrations/test_zabbix_client.py
tests/integrations/test_zabbix_service.py
tests/integrations/test_zabbix_router.py
docs/superpowers/specs/2026-08-13-zabbix-active-problems-design.md
docs/superpowers/plans/2026-08-13-zabbix-active-problems.md
```

No new router path, configuration field, migration, database model, shared contract, Wazuh/Freshservice/Snipe-IT change, Compose change, Grafana provisioning, caching, resource metric, trend, or Executive change is required.

## 13. Definition of Done

This slice is complete when an authenticated request to `/api/dashboard/zabbix` returns the existing host availability snapshot plus a bounded normalized list of unresolved Zabbix trigger problems with severity, start time, acknowledgement/suppression state, and affected hosts; all source calls remain read-only and safe failure behavior is validated.

After this slice, the next Zabbix task is CPU/memory/disk resource-pressure retrieval and normalization, followed by trends/top affected hosts, short-term caching/staleness, and the Grafana Zabbix infrastructure dashboard.
