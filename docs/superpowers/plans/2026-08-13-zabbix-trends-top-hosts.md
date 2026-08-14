# Zabbix Trends and Top Affected Hosts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic top-affected-host ranking plus a bounded 24-hour CPU/memory/disk trend to the authenticated Zabbix dashboard.

**Architecture:** Keep current host/problem/resource retrieval unchanged and concurrent. Rank at most 10 enabled hosts locally from normalized current data, then use a second bounded client phase to discover only those hosts' selected resource item IDs and issue one `trend.get` for the last 24 completed UTC hours. Pure ranking/normalization helpers remain isolated from HTTP mechanics.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, httpx, pytest, Zabbix JSON-RPC 7.4.

## Global Constraints

- Work only on `feature/zabbix-hosts`; do not implement on `main`.
- Keep the slice uncommitted until the user explicitly asks to commit.
- Production Zabbix method literals must be exactly `host.get`, `problem.get`, `trigger.get`, `item.get`, `trend.get`.
- No `history.get`, `event.get`, generic public JSON-RPC call surface, or mutation methods.
- Top affected hosts: enabled hosts only, maximum 10.
- Trend window: last 24 completed UTC hours; no route time-range parameter.
- Trend item discovery: three concurrent `item.get` calls, each bounded with a 10,001 sentinel and max 10,000 accepted rows.
- Trend selection: at most one CPU, one memory, and the currently hottest disk filesystem item per ranked host; at most 30 selected item IDs.
- `trend.get`: one request with a 721 sentinel and maximum 720 accepted rows.
- Missing trend hours are valid gaps; malformed/duplicate/unrequested/out-of-window trend rows map to `SOURCE_BAD_RESPONSE`.
- No caching/staleness, Grafana, AI, Executive aggregation, migrations, shared-contract changes, or unrelated integration changes.
- Follow strict RED -> GREEN -> REFACTOR TDD.

---

### Task 1: Top-host and trend response models plus pure ranking

**Files:**
- Modify: `app/integrations/zabbix/models.py`
- Create: `app/integrations/zabbix/top_hosts.py`
- Create: `tests/integrations/test_zabbix_top_hosts.py`

**Interfaces:**
- Consumes: `list[ZabbixHost]`, `list[ZabbixProblem]`, `list[ZabbixResourcePressure]`.
- Produces: `rank_top_affected_hosts(hosts, active_problems, resource_pressure, limit=10) -> list[ZabbixTopAffectedHost]`.
- Produces models `ZabbixTopAffectedHost`, `ZabbixResourceTrendPoint`, `ZabbixResourceTrend`, and `ResourceTrendMetric`.

- [ ] **Step 1: Write failing model/ranking tests** covering:
  - disabled hosts excluded;
  - candidate inclusion from mapped problems, unavailable interfaces, or current resource metrics;
  - highest severity rank with `unknown` above `disaster`;
  - unavailable-interface count before active-problem count;
  - peak utilization as final descending ranking input;
  - stable numeric/lexical host-ID tie-break;
  - disk peak exposes filesystem;
  - maximum 10 returned hosts;
  - no-candidate input returns `[]`.

Representative assertion shape:

```python
ranked = rank_top_affected_hosts(hosts, problems, resources)
assert [row.host_id for row in ranked] == ["2", "10"]
assert ranked[0].highest_problem_severity == "disaster"
assert ranked[0].peak_resource == "disk"
assert ranked[0].peak_filesystem == "/var"
```

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/integrations/test_zabbix_top_hosts.py -q
```

Expected: import/model/ranking failures because the new interfaces do not exist.

- [ ] **Step 3: Implement minimal models and `top_hosts.py`**
  - Severity numeric rank: `None=0`, `not_classified=1`, `information=2`, `warning=3`, `average=4`, `high=5`, `disaster=6`, `unknown=7`.
  - Count only problems whose normalized `hosts` include the host ID.
  - Count only interfaces whose availability equals `unavailable`.
  - Peak resource is max across CPU, memory, and all disk percentages; deterministic equal-value metric order is `cpu`, `memory`, then disk filesystem lexical order.
  - Sort using descending severity/unavailable/problem/peak and ascending host ID; slice to 10.

- [ ] **Step 4: Run GREEN** using the same focused test file.

---

### Task 2: Pure trend item selection and trend-row normalization

**Files:**
- Modify: `app/integrations/zabbix/resource_pressure.py`
- Create: `app/integrations/zabbix/trends.py`
- Create: `tests/integrations/test_zabbix_trends.py`

**Interfaces:**
- Produces internal immutable `ResourceTrendItemSelection` with `host_id`, `item_id`, `metric`, `invert`, and optional `filesystem`.
- Produces `select_resource_trend_items(cpu_items, memory_items, disk_items, host_ids) -> list[ResourceTrendItemSelection]`.
- Produces `completed_trend_window(now: datetime | None = None) -> tuple[int, int]`.
- Produces `normalize_resource_trends(raw_rows, selections, time_from, time_till, host_rank) -> list[ZabbixResourceTrend]`.

- [ ] **Step 1: Write failing selection/window/normalization tests** proving:
  - CPU selection uses the same aggregate-idle/newest/smallest-item-ID rule as current pressure;
  - memory prefers `pused`, falls back to `pavailable` with inversion metadata;
  - disk selects the currently hottest normalized filesystem, ties by filesystem name, then preserves `pused` preference over `pfree`;
  - only requested host IDs are selected;
  - output selection order follows requested host order then `cpu`, `memory`, `disk`;
  - completed window floors UTC current hour, subtracts 24h, and ends one second before current hour;
  - trend values invert idle/pavailable/pfree averages;
  - points sort oldest-to-newest and series follow host rank then metric order;
  - missing hours are accepted;
  - unrequested item ID, duplicate `(itemid, clock)`, non-hour-aligned clock, out-of-window clock, nonfinite/out-of-range percentage, malformed ID, and >24 points per series raise validation errors.

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/integrations/test_zabbix_trends.py tests/integrations/test_zabbix_resource_pressure.py -q
```

Expected: failures only for missing new selection/trend helpers.

- [ ] **Step 3: Refactor current pressure normalization minimally** so candidate selection is shared rather than copied. Preserve all existing `normalize_resource_pressure()` behavior/tests exactly.

- [ ] **Step 4: Implement `trends.py`** with pure window and trend normalization logic. Do not perform HTTP calls in this module.

- [ ] **Step 5: Run GREEN** for trend + current resource-pressure tests.

---

### Task 3: Bounded `list_resource_trends()` client method

**Files:**
- Modify: `app/integrations/zabbix/client.py`
- Modify: `tests/integrations/test_zabbix_client.py`

**Interfaces:**
- Produces: `ZabbixClient.list_resource_trends(host_ids: list[str]) -> list[ZabbixResourceTrend]`.
- Uses Task 2 `select_resource_trend_items`, `completed_trend_window`, and `normalize_resource_trends`.

- [ ] **Step 1: Write failing client tests** asserting:
  - `[]` host IDs returns `[]` with zero network requests;
  - duplicate host IDs deduplicate first-seen order;
  - >10 unique IDs, blank IDs, or IDs over 64 chars fail as `SOURCE_BAD_RESPONSE` before network access;
  - three `item.get` requests run concurrently and exactly match:

```python
{
    "output": ["itemid", "hostid", "key_", "lastvalue", "lastclock"],
    "hostids": host_ids,
    "monitored": True,
    "filter": {"state": "0"},
    "search": {"key_": prefix},
    "startSearch": True,
    "sortfield": "itemid",
    "limit": 10001,
}
```

  - any 10,001 item result fails with `SOURCE_BAD_RESPONSE`;
  - no selected metric items skips `trend.get`;
  - one `trend.get` uses selected item IDs and exact params:

```python
{
    "output": ["itemid", "clock", "value_avg"],
    "itemids": selected_item_ids,
    "time_from": fixed_time_from,
    "time_till": fixed_time_till,
    "limit": 721,
}
```

  - 721 trend rows fail safely;
  - pure-normalizer exceptions map to non-retryable `SOURCE_BAD_RESPONSE`;
  - existing transport retry/auth/rate-limit/error-envelope behavior is reused;
  - public client exposes `list_resource_trends` but no generic/mutation methods;
  - production method literal scan is exactly `{host.get, problem.get, trigger.get, item.get, trend.get}` and excludes `history.get`/`event.get`.

Use monkeypatch on `completed_trend_window` for deterministic request timestamps instead of adding route-controlled ranges.

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/integrations/test_zabbix_client.py -q
```

Expected: new tests fail because `list_resource_trends` and `trend.get` behavior are absent; existing client tests remain green.

- [ ] **Step 3: Implement minimal client method**
  - validate/dedupe host IDs;
  - run three bounded `item.get` reads with `asyncio.gather`;
  - select at most 30 trend items;
  - return early when none selected;
  - compute fixed completed-hour window;
  - call one bounded `_read_jsonrpc(method="trend.get", ...)`;
  - normalize with Task 2 helper;
  - map parser/model errors to `SOURCE_BAD_RESPONSE`.

- [ ] **Step 4: Run GREEN**

```bash
.venv/bin/python -m pytest tests/integrations/test_zabbix_client.py tests/integrations/test_zabbix_trends.py tests/integrations/test_zabbix_resource_pressure.py -q
```

---

### Task 4: Dashboard composition and top-host-driven trend retrieval

**Files:**
- Modify: `app/integrations/zabbix/models.py`
- Modify: `app/integrations/zabbix/service.py`
- Modify: `tests/integrations/test_zabbix_service.py`

**Interfaces:**
- `ZabbixDashboardResponse.top_affected_hosts: list[ZabbixTopAffectedHost]` max 10.
- `ZabbixDashboardResponse.resource_trends: list[ZabbixResourceTrend]` max 30.

- [ ] **Step 1: Write failing service tests** proving:
  - first-stage hosts/problems/resource-pressure calls still overlap concurrently;
  - service ranks top hosts from those normalized snapshots;
  - `list_resource_trends()` receives exactly the ranked host IDs in rank order;
  - no ranked hosts results in `list_resource_trends([])` and empty trend output;
  - returned ranking and trends are serialized into the dashboard response unchanged;
  - existing summary fields and warnings remain unchanged;
  - trend client failure propagates through the existing safe source failure behavior rather than returning a partial dashboard.

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/integrations/test_zabbix_service.py -q
```

- [ ] **Step 3: Implement minimal service/model changes**
  - keep initial `asyncio.gather(list_hosts, list_active_problems, list_resource_pressure)`;
  - call `rank_top_affected_hosts(...)`;
  - await `list_resource_trends([row.host_id for row in top_hosts])`;
  - include both new fields in `ZabbixDashboardResponse`;
  - do not change current health or warning semantics.

- [ ] **Step 4: Run GREEN** for service tests.

---

### Task 5: Route serialization regression

**Files:**
- Modify: `tests/integrations/test_zabbix_router.py`
- Production router change: none expected.

- [ ] **Step 1: Extend the fake dashboard response** with:
  - one `ZabbixTopAffectedHost` containing problem/interface/peak fields;
  - one CPU `ZabbixResourceTrend` with two hourly points;
  - one disk trend containing a filesystem.

- [ ] **Step 2: Assert JSON output** for host identity, severity, counts, peak resource metadata, trend metric/filesystem, UTC timestamps, and average-used percentages.

- [ ] **Step 3: Run**

```bash
.venv/bin/python -m pytest tests/integrations/test_zabbix_router.py -q
```

Production `app/integrations/zabbix/router.py` should remain unchanged unless this regression proves otherwise.

---

### Task 6: Feature validation and review

- [ ] Run focused Zabbix tests:

```bash
.venv/bin/python -m pytest \
  tests/integrations/test_zabbix_client.py \
  tests/integrations/test_zabbix_resource_pressure.py \
  tests/integrations/test_zabbix_trends.py \
  tests/integrations/test_zabbix_top_hosts.py \
  tests/integrations/test_zabbix_service.py \
  tests/integrations/test_zabbix_router.py -q
```

- [ ] Run full suite:

```bash
.venv/bin/python -m pytest -q
```

- [ ] Run syntax/whitespace checks:

```bash
.venv/bin/python -m compileall -q app tests
git diff --check
git diff --cached --check
```

- [ ] Verify production read-only method literals are exactly:

```text
host.get item.get problem.get trend.get trigger.get
```

- [ ] Scan production Zabbix code for mutation methods plus forbidden `history.get` and `event.get`.
- [ ] Review the final task-owned diff for credentials, auth headers, raw source bodies, unrelated integration changes, accidental time-range parameters, and all 10/24/30/720/721/10000/10001 bounds.
- [ ] Confirm working tree contains only the intended trends/top-hosts slice and leave it uncommitted.

## Definition of Done

`GET /api/dashboard/zabbix` returns the existing current host/problem/resource snapshot plus deterministic top affected enabled hosts and bounded hourly CPU/memory/disk trend series for those ranked hosts over the last 24 completed UTC hours; the only new source method is read-only `trend.get`; focused/full validation passes; and the slice remains uncommitted until explicit user instruction.
