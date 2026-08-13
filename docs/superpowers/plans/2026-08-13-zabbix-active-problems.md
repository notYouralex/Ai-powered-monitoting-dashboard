# Zabbix Active Problems Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing authenticated Zabbix dashboard endpoint with a bounded, normalized list of unresolved trigger problems, severity/acknowledgement/suppression summary counts, and affected host identities.

**Architecture:** Keep all Zabbix JSON-RPC mechanics inside `app/integrations/zabbix/`. Add `problem.get` plus `trigger.get` host resolution behind the existing read-only client, reuse the current safe transport/envelope handling through a private helper, then extend the existing dashboard models/service without changing the route path or shared contracts.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, httpx 0.28-compatible APIs, pytest, Zabbix JSON-RPC 2.0.

## Global Constraints

- Work only on `feature/zabbix-hosts`; do not implement this feature directly on `main`.
- Zabbix access remains strictly read-only. The only production JSON-RPC method literals allowed after this slice are `host.get`, `problem.get`, and `trigger.get`.
- Do not expose a public generic `request`, `call`, `create`, `update`, `delete`, or arbitrary-method client API.
- `problem.get` must request unresolved trigger problems explicitly with `recent=false`, `source=0`, and `object=0`.
- Request at most 1001 active problems and reject a 1001-record result so the application never silently truncates above its 1000-problem bound.
- If `problem.get` returns no problems, return `[]` without calling `trigger.get`.
- `trigger.get` may receive only unique trigger IDs obtained from the bounded `problem.get` result.
- Reject duplicate trigger records, unrequested trigger IDs, malformed trigger IDs, or a trigger result larger than the requested unique-trigger set.
- Accept at most 32 associated hosts per trigger. Deduplicate duplicate host IDs deterministically by first occurrence.
- A valid `problem.get` record whose trigger is absent from a valid `trigger.get` result remains visible with `hosts=[]`.
- Normalize severity `0/1/2/3/4/5` to `not_classified/information/warning/average/high/disaster`; unknown future values become `unknown`.
- Normalize `acknowledged` and `suppressed` only from source values `0` or `1`; any other value is malformed source data.
- Convert Zabbix Unix `clock` values to timezone-aware UTC `datetime` values.
- Retrieve hosts and active problems concurrently in `ZabbixDashboardService.get_dashboard()`.
- If one or more active problems cannot be mapped to a current host, keep health status `healthy` and add exactly one bounded top-level warning with singular/plural wording; never include event IDs, trigger IDs, credentials, or raw source text in warnings.
- If either the host query or problem query raises `IntegrationError`, allow the existing safe error path to fail the source request; partial-source caching/staleness is deferred.
- Do not add migrations, database models, shared contracts, Wazuh/Freshservice/Snipe-IT changes, Compose changes, Grafana provisioning, resource metrics, trends, caching, Executive aggregation, or Zabbix mutation methods.
- Preserve the current authenticated route path `GET /api/dashboard/zabbix`.
- Follow strict RED -> GREEN -> REFACTOR TDD. No new production behavior before its test has failed for the expected reason.
- Keep the Active Problems plan and implementation uncommitted until the user requests the feature commit.

---

## File Structure

- Modify `app/integrations/zabbix/models.py` — add bounded problem/host models and additive problem summary/response fields.
- Modify `app/integrations/zabbix/client.py` — add private reusable read-only JSON-RPC helper, `problem.get`, `trigger.get`, normalization, host resolution, and bounds.
- Modify `app/integrations/zabbix/service.py` — retrieve hosts/problems concurrently, calculate problem counts, return active problems, and add unmapped-host warning.
- Modify `tests/integrations/test_zabbix_client.py` — exact request shapes, normalization, bounds, error mapping, read-only surface, and no-leak regression coverage.
- Modify `tests/integrations/test_zabbix_service.py` — concurrency, severity counts, acknowledgement/suppression counts, zero problems, and warning wording.
- Modify `tests/integrations/test_zabbix_router.py` — prove the existing route serializes the additive problem fields.
- Create `docs/superpowers/plans/2026-08-13-zabbix-active-problems.md` — this task-by-task implementation plan.

---

### Task 1: Add problem models and the bounded empty `problem.get` path

**Files:**
- Modify: `tests/integrations/test_zabbix_client.py`
- Modify: `app/integrations/zabbix/models.py`
- Modify: `app/integrations/zabbix/client.py`

**Interfaces:**
- Consumes: existing `ZabbixClient.from_settings(settings, *, transport=None) -> ZabbixClient`, safe HTTP helpers, current `host.get` behavior, `IntegrationError`.
- Produces: `ZabbixProblemHost`, `ZabbixProblem`, `ZabbixProblemSeverity`, and `ZabbixClient.list_active_problems() -> list[ZabbixProblem]`.

- [ ] **Step 1: Write the first failing Active Problems client test**

Append a test that creates a `MockTransport`, calls `list_active_problems()`, and asserts the only source call is:

```python
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
```

Return an empty JSON-RPC result and assert `await client.list_active_problems() == []` and the observed method list is exactly `["problem.get"]` so `trigger.get` is not called.

- [ ] **Step 2: Run the single test and verify RED**

```bash
.venv/bin/python -m pytest tests/integrations/test_zabbix_client.py -k 'list_active_problems and skips_trigger' -q
```

Expected: FAIL because `ZabbixClient` does not yet expose `list_active_problems`.

- [ ] **Step 3: Add bounded normalized problem models**

Extend `app/integrations/zabbix/models.py` with:

```python
ZabbixProblemSeverity = Literal[
    "not_classified",
    "information",
    "warning",
    "average",
    "high",
    "disaster",
    "unknown",
]


class ZabbixProblemHost(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host_id: str = Field(min_length=1, max_length=64)
    technical_name: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=256)


class ZabbixProblem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=1, max_length=64)
    trigger_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=2048)
    severity: ZabbixProblemSeverity
    started_at: datetime
    acknowledged: bool
    suppressed: bool
    hosts: list[ZabbixProblemHost] = Field(default_factory=list, max_length=32)
```

- [ ] **Step 4: Refactor existing transport/envelope handling into a private helper**

Create:

```python
async def _read_jsonrpc(self, *, method: str, params: dict[str, Any]) -> list[Any]:
    async with create_http_client(
        timeout_seconds=self._timeout_seconds,
        verify_tls=self._verify_tls,
        ca_bundle=self._ca_bundle,
        transport=self._transport,
    ) as client:
        try:
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
                    "method": method,
                    "params": params,
                    "id": ZABBIX_REQUEST_ID,
                },
            )
        except httpx.RequestError as exc:
            raise self._source_error("SOURCE_UNAVAILABLE", retryable=True) from exc

    self._raise_for_status(response)
    payload = self._parse_payload(response)
    if payload.get("jsonrpc") != "2.0" or payload.get("id") != ZABBIX_REQUEST_ID:
        raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)

    has_result = "result" in payload
    has_error = "error" in payload
    if has_result == has_error:
        raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)
    if has_error:
        self._raise_jsonrpc_error(payload.get("error"))

    result = payload.get("result")
    if not isinstance(result, list):
        raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)
    return result
```

Move the current transport/status/envelope behavior into this helper. Update `list_hosts()` to build its existing host parameter dictionary, call `_read_jsonrpc(method="host.get", params=host_params)`, and keep its current 5000-host bound and normalization unchanged.

The helper must remain private; it is not a public arbitrary Zabbix method surface.

- [ ] **Step 5: Implement the minimal empty Active Problems path**

Add:

```python
ZABBIX_PROBLEM_LIMIT = 1000
ZABBIX_PROBLEM_SENTINEL_LIMIT = ZABBIX_PROBLEM_LIMIT + 1
ZABBIX_PROBLEM_HOST_LIMIT = 32
```

and:

```python
async def list_active_problems(self) -> list[ZabbixProblem]:
    result = await self._read_jsonrpc(
        method="problem.get",
        params={
            "output": [
                "eventid", "objectid", "clock", "name",
                "acknowledged", "severity", "suppressed",
            ],
            "recent": False,
            "source": 0,
            "object": 0,
            "sortfield": "eventid",
            "sortorder": "DESC",
            "limit": ZABBIX_PROBLEM_SENTINEL_LIMIT,
        },
    )
    if len(result) > ZABBIX_PROBLEM_LIMIT:
        raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)
    if not result:
        return []
    raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)
```

The temporary non-empty rejection is deliberate; Task 2 adds host resolution only after its tests fail.

- [ ] **Step 6: Run all client tests and verify GREEN**

```bash
.venv/bin/python -m pytest tests/integrations/test_zabbix_client.py -q
```

Expected: PASS, proving the private helper refactor preserved `host.get` and the empty `problem.get` path works.

---

### Task 2: Resolve trigger hosts and normalize non-empty active problems safely

**Files:**
- Modify: `tests/integrations/test_zabbix_client.py`
- Modify: `app/integrations/zabbix/client.py`

**Interfaces:**
- Consumes: Task 1 `list_active_problems()`, `_read_jsonrpc(*, method: str, params: dict[str, Any]) -> list[Any]`, `ZabbixProblem`, `ZabbixProblemHost`.
- Produces: complete `ZabbixClient.list_active_problems() -> list[ZabbixProblem]` behavior using exactly `problem.get` and `trigger.get`.

- [ ] **Step 1: Add reusable problem/trigger fixtures and a failing two-call happy-path test**

Add helpers that produce records with the exact source fields from the design. In the happy-path mock, return two problems sharing trigger `9001`, then assert the second call is exactly:

```python
assert body["method"] == "trigger.get"
assert body["params"] == {
    "triggerids": ["9001"],
    "output": ["triggerid"],
    "selectHosts": ["hostid", "host", "name"],
}
```

Return one trigger with one host and assert both normalized problems contain that host, severity mapping is correct, `acknowledged`/`suppressed` become booleans, and `started_at` is timezone-aware UTC.

- [ ] **Step 2: Add failing normalization and bounds tests**

Cover these cases separately:

```text
1001 problems -> SOURCE_BAD_RESPONSE
severity 0/1/2/3/4/5 -> not_classified/information/warning/average/high/disaster
severity 9 -> unknown
acknowledged 2 -> SOURCE_BAD_RESPONSE
suppressed 2 -> SOURCE_BAD_RESPONSE
blank/missing eventid -> SOURCE_BAD_RESPONSE
blank/missing objectid -> SOURCE_BAD_RESPONSE
blank/missing name -> SOURCE_BAD_RESPONSE
non-numeric or invalid clock -> SOURCE_BAD_RESPONSE
unique trigger IDs sent once in first-seen order
unrequested trigger result -> SOURCE_BAD_RESPONSE
duplicate trigger result -> SOURCE_BAD_RESPONSE
more trigger results than requested IDs -> SOURCE_BAD_RESPONSE
trigger missing triggerid -> SOURCE_BAD_RESPONSE
trigger hosts not a list -> SOURCE_BAD_RESPONSE
33 hosts on one trigger -> SOURCE_BAD_RESPONSE
host missing/blank hostid, host, or name -> SOURCE_BAD_RESPONSE
duplicate host ID -> keep first occurrence only
missing valid trigger mapping -> normalized problem with hosts=[]
```

Use `pytest.mark.parametrize` for all seven severity mappings.

- [ ] **Step 3: Add failing safe-error regression tests for new method boundaries**

Use `list_active_problems()` to prove:

```text
problem.get malformed JSON -> SOURCE_BAD_RESPONSE, raw marker absent from str/repr
problem.get HTTP 401 -> SOURCE_AUTH_FAILED, token absent from str/repr
problem.get JSON-RPC not-authorized -> SOURCE_AUTH_FAILED, raw error data absent
problem.get HTTP 429 -> 3 attempts, SOURCE_RATE_LIMITED
problem.get HTTP 503 -> 3 attempts, SOURCE_UNAVAILABLE
problem.get ConnectError -> 3 attempts, SOURCE_UNAVAILABLE
trigger.get malformed/mismatched envelope -> SOURCE_BAD_RESPONSE
trigger.get HTTP 401 -> SOURCE_AUTH_FAILED
```

- [ ] **Step 4: Strengthen the public read-only surface test**

Require `list_hosts` and `list_active_problems` to be present while continuing to forbid public `request`, `call`, `create`, `update`, and `delete`. Add a narrow source scan proving production Zabbix method literals are exactly `host.get`, `problem.get`, and `trigger.get`.

- [ ] **Step 5: Run client tests and verify RED**

```bash
.venv/bin/python -m pytest tests/integrations/test_zabbix_client.py -q
```

Expected: new non-empty/normalization/trigger tests fail because Task 1 still rejects non-empty results.

- [ ] **Step 6: Implement unique trigger extraction, host normalization, and problem normalization**

Add:

```python
_PROBLEM_SEVERITIES: dict[str, ZabbixProblemSeverity] = {
    "0": "not_classified",
    "1": "information",
    "2": "warning",
    "3": "average",
    "4": "high",
    "5": "disaster",
}
```

Implement `_unique_problem_trigger_ids(items)` using `_required_string(item.get("objectid"))`, a `seen` set, and first-seen ordering.

Implement `_normalize_problem_hosts(items)` to require object records with non-empty `hostid`, `host`, and `name`, deduplicate by host ID while retaining the first record, and return `list[ZabbixProblemHost]`.

Implement `_normalize_trigger_hosts(items, *, requested)` to reject more results than requested, unrequested/duplicate trigger IDs, non-list `hosts`, and more than 32 hosts; return `dict[str, list[ZabbixProblemHost]]`.

Implement:

```python
@staticmethod
def _normalize_problem(
    item: Any,
    *,
    hosts_by_trigger: dict[str, list[ZabbixProblemHost]],
) -> ZabbixProblem:
    if not isinstance(item, dict):
        raise TypeError("problem item must be an object")
    trigger_id = _required_string(item.get("objectid"))
    return ZabbixProblem(
        event_id=_required_string(item.get("eventid")),
        trigger_id=trigger_id,
        name=_required_string(item.get("name")),
        severity=_PROBLEM_SEVERITIES.get(str(item.get("severity")), "unknown"),
        started_at=datetime.fromtimestamp(int(item.get("clock")), tz=timezone.utc),
        acknowledged=_binary_bool(item.get("acknowledged"), true_value="1"),
        suppressed=_binary_bool(item.get("suppressed"), true_value="1"),
        hosts=hosts_by_trigger.get(trigger_id, []),
    )
```

Then replace the temporary non-empty rejection with one `trigger.get` call for unique IDs and normalize all problem records inside a safe exception mapping that includes `KeyError`, `TypeError`, `ValueError`, `OverflowError`, and `ValidationError` -> `SOURCE_BAD_RESPONSE`.

- [ ] **Step 7: Run all client tests and verify GREEN**

```bash
.venv/bin/python -m pytest tests/integrations/test_zabbix_client.py -q
git diff --check
```

Expected: PASS / exit 0.

---

### Task 3: Add Active Problems to dashboard models and service

**Files:**
- Modify: `tests/integrations/test_zabbix_service.py`
- Modify: `app/integrations/zabbix/models.py`
- Modify: `app/integrations/zabbix/service.py`

**Interfaces:**
- Consumes: `list_hosts()` and `list_active_problems()`.
- Produces: additive problem summary fields, `active_problems`, concurrent retrieval, and unmapped-host warning.

- [ ] **Step 1: Extend the fake service client and add a failing concurrency test**

Give the fake client both methods and counters. Add a `CoordinatedClient` test where `list_hosts()` sets `host_started`, awaits `asyncio.wait_for(problem_started.wait(), timeout=0.2)`, and returns `[]`; `list_active_problems()` sets `problem_started`, awaits `asyncio.wait_for(host_started.wait(), timeout=0.2)`, and returns `[]`. Assert the resulting dashboard has zero hosts and zero problems. This fails with sequential retrieval and passes only when the service uses `asyncio.gather`.

- [ ] **Step 2: Add failing problem summary and warning tests**

Create a `problem(event_id: str, *, severity: str, acknowledged: bool = False, suppressed: bool = False, mapped: bool = True) -> ZabbixProblem` test helper that returns one mapped `ZabbixProblemHost` when `mapped=True` and `hosts=[]` otherwise. Build seven problems covering every severity bucket and assert:

```python
assert response.summary.problems_total == 7
assert response.summary.problems_not_classified == 1
assert response.summary.problems_information == 1
assert response.summary.problems_warning == 1
assert response.summary.problems_average == 1
assert response.summary.problems_high == 1
assert response.summary.problems_disaster == 1
assert response.summary.problems_unknown == 1
```

Choose acknowledgement/suppression fixture values that produce deterministic assertions for `problems_unacknowledged` and `problems_suppressed`, and assert `response.active_problems == problems`.

Extend the empty snapshot test so every problem summary count is zero, `active_problems == []`, and `warnings == []`.

Add warning tests for exactly:

```text
1 active Zabbix problem could not be mapped to a current host.
2 active Zabbix problems could not be mapped to a current host.
```

and assert health remains `healthy`.

- [ ] **Step 3: Run service tests and verify RED**

```bash
.venv/bin/python -m pytest tests/integrations/test_zabbix_service.py -q
```

Expected: FAIL because problem dashboard fields and concurrent retrieval do not exist yet.

- [ ] **Step 4: Extend the dashboard models additively**

Add to `ZabbixDashboardSummary`:

```python
problems_total: int = Field(ge=0)
problems_not_classified: int = Field(ge=0)
problems_information: int = Field(ge=0)
problems_warning: int = Field(ge=0)
problems_average: int = Field(ge=0)
problems_high: int = Field(ge=0)
problems_disaster: int = Field(ge=0)
problems_unknown: int = Field(ge=0)
problems_unacknowledged: int = Field(ge=0)
problems_suppressed: int = Field(ge=0)
```

Add to `ZabbixDashboardResponse`:

```python
active_problems: list[ZabbixProblem] = Field(default_factory=list, max_length=1000)
```

Keep all host/interface fields unchanged.

- [ ] **Step 5: Implement concurrent retrieval and summary/warning calculation**

Use:

```python
hosts, active_problems = await asyncio.gather(
    self._client.list_hosts(),
    self._client.list_active_problems(),
)
```

Change `_build_summary` to accept both lists, preserve existing host/interface counts, count each problem severity, count `not problem.acknowledged`, and count `problem.suppressed`.

Add:

```python
def _build_warnings(active_problems: list[ZabbixProblem]) -> list[str]:
    unmapped = sum(1 for problem in active_problems if not problem.hosts)
    if unmapped == 0:
        return []
    if unmapped == 1:
        return ["1 active Zabbix problem could not be mapped to a current host."]
    return [f"{unmapped} active Zabbix problems could not be mapped to a current host."]
```

Return these warnings only at the top-level response; keep `health.status="healthy"` and `health.warnings=[]`.

- [ ] **Step 6: Run client + service tests and verify GREEN**

```bash
.venv/bin/python -m pytest \
  tests/integrations/test_zabbix_client.py \
  tests/integrations/test_zabbix_service.py -q
```

Expected: PASS.

---

### Task 4: Serialize Active Problems through the existing authenticated route

**Files:**
- Modify: `tests/integrations/test_zabbix_router.py`
- Production router change: none expected.

**Interfaces:**
- Consumes: existing `GET /api/dashboard/zabbix` and `ZabbixDashboardResponse`.
- Produces: regression proof that the unchanged route serializes additive problem fields.

- [ ] **Step 1: Extend `FakeDashboardService` with one normalized problem**

Import `ZabbixProblem` and `ZabbixProblemHost`. Supply every new `ZabbixDashboardSummary` field and add one `active_problems` record with severity `high` and one host.

- [ ] **Step 2: Extend response assertions**

Assert:

```python
assert body["summary"]["problems_total"] == 1
assert body["summary"]["problems_high"] == 1
assert body["summary"]["problems_unacknowledged"] == 1
assert body["active_problems"][0]["event_id"] == "7001"
assert body["active_problems"][0]["severity"] == "high"
assert body["active_problems"][0]["hosts"][0]["host_id"] == "10001"
```

- [ ] **Step 3: Run router tests and verify GREEN**

```bash
.venv/bin/python -m pytest tests/integrations/test_zabbix_router.py -q
```

Expected: PASS. Authentication, unconfigured handling, and route mounting remain unchanged.

---

### Task 5: Feature-level validation and diff review

**Files:**
- Review all task-owned files; add no production behavior.

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: fresh evidence that the slice is bounded, read-only, safe, and regression-free.

- [ ] **Step 1: Run focused Zabbix tests**

```bash
.venv/bin/python -m pytest \
  tests/integrations/test_zabbix_client.py \
  tests/integrations/test_zabbix_service.py \
  tests/integrations/test_zabbix_router.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the full available suite**

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS. If an environment dependency blocks collection, record the exact blocker and do not claim the full suite passed.

- [ ] **Step 3: Run syntax/whitespace validation**

```bash
.venv/bin/python -m compileall -q app tests
git diff --check
git diff --cached --check
```

Expected: all exit 0.

- [ ] **Step 4: Verify production Zabbix code remains read-only**

```bash
grep -RInE 'host\.(create|update|delete|massupdate)|item\.(create|update|delete)|trigger\.(create|update|delete)|event\.acknowledge|hostinterface\.(create|update|delete|mass)' app/integrations/zabbix && exit 1 || true
```

Expected: no matches. Also inspect production method literals and confirm the semantic set is exactly `host.get`, `problem.get`, `trigger.get`.

- [ ] **Step 5: Scan task-owned changes for secret/raw-source leakage**

Review the diff and search for private-key headers, authorization logging/printing, raw response logging, and real token strings. Clearly fake test tokens are allowed only in test fixtures.

- [ ] **Step 6: Review Git status and leave the feature uncommitted**

```bash
git status --short --branch
```

Expected: `feature/zabbix-hosts` with only the approved Active Problems plan/implementation/tests modified. Do not commit until the user requests the feature commit.

---

## Definition of Done

The Active Problems slice is complete when authenticated `GET /api/dashboard/zabbix` returns the existing host/interface snapshot plus at most 1000 normalized unresolved trigger problems with severity, UTC start time, acknowledgement/suppression state, and affected hosts; host/problem reads run concurrently; missing trigger-host mappings produce one safe warning instead of breaking the response; only `host.get`, `problem.get`, and `trigger.get` are callable in production Zabbix code; and focused/full available validation is green.

After this slice, the next Zabbix task is CPU/memory/disk resource-pressure retrieval and normalization, followed by trends/top affected hosts, short-term caching/staleness, and the Grafana Zabbix infrastructure dashboard.
