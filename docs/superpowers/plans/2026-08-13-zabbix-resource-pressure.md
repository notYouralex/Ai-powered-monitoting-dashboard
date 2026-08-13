# Zabbix Resource Pressure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add bounded, read-only current CPU, memory, and disk utilization to the authenticated Zabbix dashboard.

**Architecture:** `ZabbixClient` runs three concurrent bounded `item.get` reads and delegates pure parsing/selection to `resource_pressure.py`. `ZabbixDashboardService` retrieves hosts, active problems, and resource pressure concurrently, adds coverage counts/warnings, and keeps the existing route unchanged.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, httpx, pytest, Zabbix JSON-RPC 7.4.

## Global Constraints

- Read-only Zabbix methods only: `host.get`, `problem.get`, `trigger.get`, `item.get`.
- Each resource query uses a 10,001 sentinel and accepts at most 10,000 rows.
- Maximum 64 normalized filesystems per host and 5,000 resource hosts per response.
- Missing current values are skipped; malformed recognized current values map to `SOURCE_BAD_RESPONSE`.
- Trends, thresholds, top-host ranking, caching/staleness, Grafana, and Executive aggregation are out of scope.
- Keep this slice uncommitted until the user explicitly asks to commit.

---

### Task 1: Resource models and pure normalization

**Files:**
- Modify: `app/integrations/zabbix/models.py`
- Create: `app/integrations/zabbix/resource_pressure.py`
- Create: `tests/integrations/test_zabbix_resource_pressure.py`

**Interfaces:**
- Consumes: raw CPU/memory/disk `item.get` result lists.
- Produces: `normalize_resource_pressure(cpu_items, memory_items, disk_items) -> list[ZabbixResourcePressure]`.

- [ ] **Step 1: Write failing tests** for CPU idle inversion, memory `pused` plus `pavailable` fallback, disk `pused` plus `pfree` fallback, UTC clocks, deterministic candidate selection, skipped blank values, invalid recognized values, ignored unsupported keys, 64-filesystem bound, and stable ordering.
- [ ] **Step 2: Run RED:** `.venv/bin/python -m pytest tests/integrations/test_zabbix_resource_pressure.py -q`.
- [ ] **Step 3: Implement minimal models/normalizer** required by those tests.
- [ ] **Step 4: Run GREEN:** the same command must pass.

---

### Task 2: Bounded concurrent `item.get` client reads

**Files:**
- Modify: `app/integrations/zabbix/client.py`
- Modify: `tests/integrations/test_zabbix_client.py`

**Interfaces:**
- Produces: `ZabbixClient.list_resource_pressure() -> list[ZabbixResourcePressure]`.

- [ ] **Step 1: Write failing client tests** asserting three exact requests with prefixes `system.cpu.util`, `vm.memory.size`, and `vfs.fs.size`. Each request must use output `itemid,hostid,key_,lastvalue,lastclock`, `monitored=true`, `filter.state=0`, `startSearch=true`, `sortfield=itemid`, and `limit=10001`.
- [ ] Prove the three reads overlap concurrently, each sentinel overflow fails safely, normalizer failures map to `SOURCE_BAD_RESPONSE`, and the production method set is exactly `{host.get, problem.get, trigger.get, item.get}`.
- [ ] **Step 2: Run RED:** `.venv/bin/python -m pytest tests/integrations/test_zabbix_client.py -q`.
- [ ] **Step 3: Implement minimal `list_resource_pressure()`** using `asyncio.gather`, per-result bounds, and the pure normalizer.
- [ ] **Step 4: Run GREEN:** client + resource-pressure tests together.

---

### Task 3: Dashboard service, summary, and warnings

**Files:**
- Modify: `app/integrations/zabbix/models.py`
- Modify: `app/integrations/zabbix/service.py`
- Modify: `tests/integrations/test_zabbix_service.py`

- [ ] **Step 1: Write failing tests** proving hosts/problems/resource-pressure are retrieved concurrently, coverage counts are correct, resource records are returned unchanged, and missing CPU/memory/disk warnings count enabled hosts only without degrading health.
- [ ] Add summary expectations for `resource_hosts_total`, `resource_hosts_with_cpu`, `resource_hosts_with_memory`, and `resource_hosts_with_disk`.
- [ ] **Step 2: Run RED:** `.venv/bin/python -m pytest tests/integrations/test_zabbix_service.py -q`.
- [ ] **Step 3: Implement minimal service/model changes**, including `resource_pressure: list[ZabbixResourcePressure]` with max length 5,000.
- [ ] **Step 4: Run GREEN:** service tests pass.

---

### Task 4: Route serialization regression

**Files:**
- Modify: `tests/integrations/test_zabbix_router.py`
- Production router change: none expected.

- [ ] Extend the fake response with one resource-pressure host and all new summary fields.
- [ ] Assert JSON serialization of CPU/memory percentages, disk filesystem/percentage, timestamp, and coverage counts.
- [ ] Run `.venv/bin/python -m pytest tests/integrations/test_zabbix_router.py -q` and keep the production router unchanged unless the test proves otherwise.

---

### Task 5: Feature validation and review

- [ ] Run focused Zabbix tests: client, resource-pressure, service, and router.
- [ ] Run full suite: `.venv/bin/python -m pytest -q`.
- [ ] Run `.venv/bin/python -m compileall -q app tests`, `git diff --check`, and `git diff --cached --check`.
- [ ] Scan production Zabbix code for mutation methods and confirm only `host.get`, `problem.get`, `trigger.get`, and `item.get` are present semantically.
- [ ] Review task-owned diff for secrets, auth-header/raw-response logging, unrelated files, and bounds.
- [ ] Leave the complete slice uncommitted until explicit user instruction.

## Definition of Done

`GET /api/dashboard/zabbix` returns existing host/problem data plus bounded current CPU, memory, and disk utilization; resource reads are concurrent and read-only; missing enabled-host coverage produces bounded warnings; focused/full validation passes; and only intended resource-pressure files remain uncommitted.
