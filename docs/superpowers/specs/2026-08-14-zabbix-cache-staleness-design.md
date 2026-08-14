# Zabbix Cache and Staleness Design

## Goal

Add a short-term PostgreSQL-backed cache for the normalized Zabbix dashboard so the API can continue showing the last successful snapshot when a later Zabbix refresh fails. The worker owns refreshes; the dashboard API reads cached normalized data and reports freshness explicitly.

## Requirements and constraints

- Zabbix remains strictly read-only at the source.
- Persist only the validated `ZabbixDashboardResponse` JSON payload, never raw Zabbix responses, credentials, authorization headers, or source error text.
- A failed refresh must not overwrite or delete the last successful snapshot.
- Reuse the existing `sync_runs` table for refresh success/failure metadata.
- Add a new additive migration after current head `0002_freshservice_sync`; do not edit merged migrations.
- Keep this slice Zabbix-focused. No Grafana, AI, Executive aggregation, Wazuh, Freshservice, or Snipe-IT behavior changes.
- Preserve the current live `ZabbixDashboardService` as the normalized source builder used by the refresh worker.

## Persistence

Create one Zabbix-owned table, `zabbix_dashboard_cache`, with a fixed singleton row (`id=1`), a JSON `snapshot` column, and `refreshed_at` UTC timestamp. The JSON is produced with `ZabbixDashboardResponse.model_dump(mode="json")` and is revalidated with `ZabbixDashboardResponse.model_validate(...)` when read.

Refresh attempts create `SyncRun` rows with `source="zabbix"` and `sync_type="snapshot"`. Successful refreshes atomically replace the singleton normalized snapshot and mark the run successful. Integration failures mark only the run failed with the safe error code and leave the cached snapshot untouched. Database failures roll back and record `SYNC_DATABASE_ERROR` where possible.

## Freshness semantics

The worker refresh interval is a Zabbix-owned constant of 60 seconds. Cached data becomes stale after 120 seconds (two expected refresh intervals).

When a cache exists:

- latest refresh successful and age <= 120 seconds: `health.status="healthy"`, `is_stale=False`;
- latest refresh failed after the cached success: `health.status="degraded"`, `is_stale=True`, warning that the last successful data is being shown;
- cached snapshot older than 120 seconds: `health.status="degraded"`, `is_stale=True`, warning that data is older than the expected refresh window;
- Zabbix configuration removed while cache exists: `health.status="not_configured"`, `is_stale=True`, warning that previous cached data is being shown.

The top-level Zabbix response gains `is_stale: bool = False`. `observed_at` continues to represent the data snapshot time. `health.observed_at` represents the current cache-read time, and `health.last_success_at` is the cache `refreshed_at` timestamp.

If no successful cache exists, the API must not invent data. An unconfigured source raises the existing safe `SOURCE_NOT_CONFIGURED` error; a configured source with no successful snapshot raises safe retryable `SOURCE_UNAVAILABLE`.

## Components

- `app/db/models.py`: `ZabbixDashboardCache` ORM model.
- `migrations/versions/0003_zabbix_dashboard_cache.py`: additive cache table migration.
- `app/integrations/zabbix/cache.py`: refresh/persistence service, cached dashboard reader, freshness calculation, refresh/stale constants.
- `app/integrations/zabbix/models.py`: add top-level `is_stale`.
- `app/integrations/zabbix/router.py`: read from PostgreSQL cache via DB/settings dependency instead of calling Zabbix live.
- `app/worker.py`: add periodic Zabbix refresh loop alongside the existing Freshservice synchronization loop.

## Testing

Use TDD. Cover successful cache insert/replacement, failed refresh preserving the old snapshot, safe failure codes, healthy/degraded/stale/not-configured reads, no-cache errors, router serialization, worker skip/configured behavior, migration/model shape, and regression of the full existing Zabbix suite. Final validation includes the full repository suite, compileall, Alembic heads, whitespace checks, read-only method scan, and secret/raw-source review.
