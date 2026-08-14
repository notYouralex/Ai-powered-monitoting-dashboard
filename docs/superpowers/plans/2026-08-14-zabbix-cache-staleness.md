# Zabbix Cache and Staleness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist worker-refreshed normalized Zabbix dashboard snapshots in PostgreSQL and serve the last successful snapshot with explicit stale/degraded health when later refreshes fail.

**Architecture:** Keep `ZabbixDashboardService` as the live normalized source builder. Add a Zabbix cache service that writes one validated JSON snapshot plus `sync_runs` metadata, and a cached reader used by the API. Add a 60-second Zabbix loop to the existing worker; stale age is 120 seconds.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL/SQLite test database, pytest.

## Global Constraints

- Source API remains read-only; production JSON-RPC methods stay exactly `host.get`, `item.get`, `problem.get`, `trend.get`, `trigger.get`.
- Store only normalized `ZabbixDashboardResponse` JSON, never raw responses or secrets.
- Refresh interval: 60 seconds. Stale threshold: 120 seconds.
- Failed refresh never mutates the last successful cache row.
- Reuse `sync_runs`; add only new migration `0003_zabbix_dashboard_cache` after `0002_freshservice_sync`.
- No Grafana, AI, Executive, Wazuh, Freshservice data-model, or Snipe-IT changes.
- Do not commit or push until the user explicitly requests it.

---

### Task 1: Cache persistence model and migration

**Files:**
- Modify: `app/db/models.py`
- Create: `migrations/versions/0003_zabbix_dashboard_cache.py`
- Modify: `tests/test_models.py`

**Interfaces:**
- Produces ORM `ZabbixDashboardCache(id: int, snapshot: dict, refreshed_at: datetime)` with singleton row id `1`.

- [ ] **Step 1: Write a failing model test** that creates `Base.metadata`, persists `ZabbixDashboardCache(id=1, snapshot={"source":"zabbix"}, refreshed_at=...)`, reloads it, and asserts JSON/timestamp round-trip.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_models.py -q` and verify RED because the model does not exist.
- [ ] **Step 3: Implement** SQLAlchemy `JSON`-backed `ZabbixDashboardCache` and migration `0003_zabbix_dashboard_cache` with `down_revision="0002_freshservice_sync"`.
- [ ] **Step 4: Run** model tests plus `.venv/bin/python -m alembic heads`; expect tests GREEN and one head `0003_zabbix_dashboard_cache`.

---

### Task 2: Refresh service preserves last valid normalized snapshot

**Files:**
- Create: `app/integrations/zabbix/cache.py`
- Create: `tests/integrations/test_zabbix_cache.py`

**Interfaces:**
- `ZABBIX_CACHE_REFRESH_INTERVAL_SECONDS = 60`
- `ZABBIX_CACHE_STALE_AFTER_SECONDS = 120`
- `class ZabbixCacheRefreshService(client, clock=utc_now)`
- `async refresh(db: Session) -> SyncRun`

- [ ] **Step 1: Write failing tests** proving first success creates singleton snapshot + successful `SyncRun`, second success replaces the singleton rather than adding another row, source `IntegrationError` records failed run and preserves old snapshot byte-for-byte, and database persistence failure does not erase old cache.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/integrations/test_zabbix_cache.py -q` and verify RED.
- [ ] **Step 3: Implement** refresh with `ZabbixDashboardService(client).get_dashboard()`, `model_dump(mode="json")`, singleton upsert, safe run metadata, rollback on SQLAlchemy error, and `_mark_failed` mirroring the established Freshservice sync pattern.
- [ ] **Step 4: Run** cache tests and verify GREEN.

---

### Task 3: Cached dashboard read and staleness semantics

**Files:**
- Modify: `app/integrations/zabbix/cache.py`
- Modify: `app/integrations/zabbix/models.py`
- Modify: `tests/integrations/test_zabbix_cache.py`

**Interfaces:**
- Add `ZabbixDashboardResponse.is_stale: bool = False`.
- `class ZabbixCachedDashboardService(db: Session, settings: Settings, clock=utc_now)`
- `get_dashboard() -> ZabbixDashboardResponse`

- [ ] **Step 1: Write failing tests** for healthy fresh cache, latest failed refresh => degraded/stale, age >120s => degraded/stale, unconfigured-with-cache => not_configured/stale, configured-without-cache => retryable `SOURCE_UNAVAILABLE`, and unconfigured-without-cache => nonretryable `SOURCE_NOT_CONFIGURED`.
- [ ] **Step 2: Run cache tests** and verify RED.
- [ ] **Step 3: Implement** cache model validation, latest-run lookup, safe warning merge, current `health.observed_at`, `last_success_at=refreshed_at`, preserved snapshot `observed_at`, and top-level `is_stale`.
- [ ] **Step 4: Run cache + service tests** and verify GREEN.

---

### Task 4: Router serves cached normalized snapshots

**Files:**
- Modify: `app/integrations/zabbix/router.py`
- Modify: `tests/integrations/test_zabbix_router.py`

**Interfaces:**
- Preserve dependency name `get_zabbix_dashboard_service` so existing override tests remain stable.
- Dependency consumes `Session = Depends(get_db)` and `Settings = Depends(get_settings)` and returns `ZabbixCachedDashboardService`.

- [ ] **Step 1: Add failing router tests** that seed `ZabbixDashboardCache`/`SyncRun` and verify authenticated JSON contains cached data plus `is_stale`, degraded health, `last_success_at`, and safe stale warning.
- [ ] **Step 2: Run router tests** and verify RED because the route still calls Zabbix live.
- [ ] **Step 3: Implement minimal router dependency switch**; do not change route path/authentication/response model.
- [ ] **Step 4: Run router tests** and verify GREEN.

---

### Task 5: Worker refresh scheduling

**Files:**
- Modify: `app/worker.py`
- Modify: `tests/test_freshservice_worker.py`
- Create: `tests/test_zabbix_worker.py`

**Interfaces:**
- `async run_zabbix_refresh_once(*, settings, session_factory=SessionLocal, client_factory=ZabbixClient.from_settings) -> str`
- Worker runs independent Freshservice and Zabbix periodic loops concurrently; Freshservice cadence remains settings-controlled, Zabbix cadence is 60 seconds.

- [ ] **Step 1: Write failing tests** proving unconfigured Zabbix skips client creation, configured refresh delegates to cache refresh and returns its run status, and existing Freshservice one-shot behavior remains unchanged.
- [ ] **Step 2: Run worker tests** and verify RED for missing Zabbix function.
- [ ] **Step 3: Implement** one-shot refresh and separate periodic loops with safe `IntegrationError`/`SQLAlchemyError` logging containing codes only, then `asyncio.gather` them in `run_worker()`.
- [ ] **Step 4: Run worker tests** and verify GREEN.

---

### Task 6: Full validation and review

- [ ] Run focused Zabbix/cache/worker/model tests.
- [ ] Run `.venv/bin/python -m pytest -q`.
- [ ] Run `.venv/bin/python -m compileall -q app tests`.
- [ ] Run `.venv/bin/python -m alembic heads` and confirm exactly `0003_zabbix_dashboard_cache (head)`.
- [ ] Run `git diff --check` and `git diff --cached --check`.
- [ ] Verify production JSON-RPC method literals remain exactly `host.get item.get problem.get trend.get trigger.get` and no write/history/event methods were introduced.
- [ ] Review final diff for credentials, authorization headers, raw Zabbix bodies, unrelated integration changes, migration conflicts, and cache bounds/cadence.
- [ ] Leave all cache work uncommitted and unpushed.
