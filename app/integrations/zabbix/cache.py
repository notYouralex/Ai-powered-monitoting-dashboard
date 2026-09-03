from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.contracts import ExecutiveSourceSummary
from app.core.config import Settings
from app.core.errors import IntegrationError
from app.db.models import SyncRun, ZabbixDashboardCache
from app.integrations.zabbix.client import ZabbixClient
from app.integrations.zabbix.models import (
    ZabbixDashboardResponse,
    ZabbixNetworkLivePoint,
    ZabbixNetworkLiveSeries,
    ZabbixResourceLivePoint,
    ZabbixResourceLiveSeries,
)
from app.integrations.zabbix.service import ZabbixDashboardService


ZABBIX_CACHE_REFRESH_INTERVAL_SECONDS = 60
ZABBIX_CACHE_STALE_AFTER_SECONDS = ZABBIX_CACHE_REFRESH_INTERVAL_SECONDS * 2
ZABBIX_LIVE_WINDOW_SECONDS = 60 * 60
ZABBIX_LIVE_MAX_POINTS = 60
ZABBIX_CACHE_ROW_ID = 1


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ZabbixCacheRefreshService:
    """Persist validated normalized Zabbix dashboard snapshots without source-side writes."""

    def __init__(
        self,
        client: ZabbixClient,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._client = client
        self._clock = clock

    async def refresh(self, db: Session) -> SyncRun:
        run = SyncRun(
            source="zabbix",
            sync_type="snapshot",
            status="running",
            started_at=self._clock(),
            records_received=0,
            records_upserted=0,
        )
        db.add(run)
        db.commit()
        run_id = run.id

        try:
            dashboard = await ZabbixDashboardService(client=self._client).get_dashboard()
        except IntegrationError as exc:
            self._mark_failed(db, run_id, exc.code)
            raise

        completed_at = self._clock()
        try:
            cached = db.get(ZabbixDashboardCache, ZABBIX_CACHE_ROW_ID)
            previous_live: list[ZabbixResourceLiveSeries] = []
            previous_network_live: list[ZabbixNetworkLiveSeries] = []
            if cached is not None:
                try:
                    previous = ZabbixDashboardResponse.model_validate(cached.snapshot)
                except ValidationError:
                    previous = None
                if previous is not None:
                    previous_live = previous.resource_live
                    previous_network_live = previous.network_live

            dashboard = dashboard.model_copy(
                update={
                    "resource_live": _merge_resource_live(
                        previous_live,
                        dashboard.resource_live,
                        observed_at=completed_at,
                    ),
                    "network_live": _merge_network_live(
                        previous_network_live,
                        dashboard.network_live,
                        observed_at=completed_at,
                    ),
                }
            )
            if cached is None:
                cached = ZabbixDashboardCache(
                    id=ZABBIX_CACHE_ROW_ID,
                    snapshot=dashboard.model_dump(mode="json"),
                    refreshed_at=completed_at,
                )
                db.add(cached)
            else:
                cached.snapshot = dashboard.model_dump(mode="json")
                cached.refreshed_at = completed_at

            persisted_run = db.get(SyncRun, run_id)
            if persisted_run is None:
                raise RuntimeError("Zabbix refresh run disappeared")
            persisted_run.status = "success"
            persisted_run.completed_at = completed_at
            persisted_run.records_received = 1
            persisted_run.records_upserted = 1
            persisted_run.error_code = None
            db.commit()
            return persisted_run
        except SQLAlchemyError:
            db.rollback()
            self._mark_failed(db, run_id, "SYNC_DATABASE_ERROR")
            raise

    def _mark_failed(self, db: Session, run_id: int, error_code: str) -> None:
        run = db.get(SyncRun, run_id)
        if run is None:
            return
        run.status = "failed"
        run.completed_at = self._clock()
        run.error_code = error_code[:64]
        run.records_upserted = 0
        db.commit()


class ZabbixCachedDashboardService:
    """Build the Grafana-facing Zabbix response from the last valid normalized cache."""

    def __init__(
        self,
        db: Session,
        settings: Settings,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._db = db
        self._settings = settings
        self._clock = clock

    def get_dashboard(self) -> ZabbixDashboardResponse:
        now = self._clock()
        cached = self._db.get(ZabbixDashboardCache, ZABBIX_CACHE_ROW_ID)
        configured = self._settings.integration_config_state("zabbix") == "configured"

        if cached is None:
            if not configured:
                raise IntegrationError(
                    source="zabbix",
                    code="SOURCE_NOT_CONFIGURED",
                    retryable=False,
                )
            raise IntegrationError(
                source="zabbix",
                code="SOURCE_UNAVAILABLE",
                retryable=True,
            )

        try:
            response = ZabbixDashboardResponse.model_validate(cached.snapshot)
        except ValidationError as exc:
            raise IntegrationError(
                source="zabbix",
                code="SOURCE_BAD_RESPONSE",
                retryable=False,
            ) from exc

        status = "healthy"
        is_stale = False
        state_warnings: list[str] = []
        latest_run = self._latest_run()
        last_success = self._latest_success()

        if not configured:
            status = "not_configured"
            is_stale = True
            state_warnings.append(
                "Zabbix is not configured; showing previously cached data."
            )
        else:
            if (
                latest_run is not None
                and latest_run.status == "failed"
                and (last_success is None or latest_run.id != last_success.id)
            ):
                status = "degraded"
                is_stale = True
                state_warnings.append(
                    "The latest Zabbix refresh failed; showing last successful cached data."
                )

            if now - cached.refreshed_at > timedelta(seconds=ZABBIX_CACHE_STALE_AFTER_SECONDS):
                status = "degraded"
                is_stale = True
                state_warnings.append(
                    "Zabbix cached data is older than the expected refresh window."
                )

        health = response.health.model_copy(
            update={
                "status": status,
                "observed_at": now,
                "last_success_at": cached.refreshed_at,
                "is_stale": is_stale,
                "warnings": state_warnings,
            }
        )
        return response.model_copy(
            update={
                "is_stale": is_stale,
                "health": health,
                "warnings": _merge_warnings(response.warnings, state_warnings),
            }
        )

    def get_executive_summary(self) -> ExecutiveSourceSummary:
        dashboard = self.get_dashboard()
        summary = dashboard.summary

        return ExecutiveSourceSummary(
            source="zabbix",
            observed_at=dashboard.observed_at,
            is_stale=dashboard.is_stale,
            health=dashboard.health,
            metrics={
                "hosts_total": summary.hosts_total,
                "hosts_enabled": summary.hosts_enabled,
                "hosts_disabled": summary.hosts_disabled,
                "hosts_in_maintenance": summary.hosts_in_maintenance,
                "interfaces_unavailable": summary.interfaces_unavailable,
                "problems_total": summary.problems_total,
                "problems_high": summary.problems_high,
                "problems_disaster": summary.problems_disaster,
                "problems_unacknowledged": summary.problems_unacknowledged,
                "resource_hosts_total": summary.resource_hosts_total,
                "resource_hosts_with_cpu": summary.resource_hosts_with_cpu,
                "resource_hosts_with_memory": summary.resource_hosts_with_memory,
                "resource_hosts_with_disk": summary.resource_hosts_with_disk,
            },
            warnings=dashboard.warnings,
        )

    def _latest_run(self) -> SyncRun | None:
        return self._db.scalar(
            select(SyncRun)
            .where(SyncRun.source == "zabbix")
            .order_by(SyncRun.started_at.desc(), SyncRun.id.desc())
            .limit(1)
        )

    def _latest_success(self) -> SyncRun | None:
        return self._db.scalar(
            select(SyncRun)
            .where(SyncRun.source == "zabbix", SyncRun.status == "success")
            .order_by(SyncRun.completed_at.desc(), SyncRun.id.desc())
            .limit(1)
        )


def _merge_resource_live(
    previous: list[ZabbixResourceLiveSeries],
    current: list[ZabbixResourceLiveSeries],
    *,
    observed_at: datetime,
) -> list[ZabbixResourceLiveSeries]:
    cutoff = observed_at - timedelta(seconds=ZABBIX_LIVE_WINDOW_SECONDS)
    previous_by_key = {(row.host_id, row.metric): row for row in previous}
    merged: list[ZabbixResourceLiveSeries] = []

    for current_series in current:
        key = (current_series.host_id, current_series.metric)
        points_by_time: dict[datetime, ZabbixResourceLivePoint] = {}
        previous_series = previous_by_key.get(key)
        if previous_series is not None:
            for point in previous_series.points:
                if point.observed_at >= cutoff:
                    points_by_time[point.observed_at] = point
        for point in current_series.points:
            if point.observed_at >= cutoff:
                points_by_time[point.observed_at] = point

        points = sorted(points_by_time.values(), key=lambda point: point.observed_at)
        points = points[-ZABBIX_LIVE_MAX_POINTS:]
        if points:
            merged.append(current_series.model_copy(update={"points": points}))

    return merged


def _merge_network_live(
    previous: list[ZabbixNetworkLiveSeries],
    current: list[ZabbixNetworkLiveSeries],
    *,
    observed_at: datetime,
) -> list[ZabbixNetworkLiveSeries]:
    cutoff = observed_at - timedelta(seconds=ZABBIX_LIVE_WINDOW_SECONDS)
    previous_by_key = {
        (row.host_id, row.metric, row.interface): row for row in previous
    }
    merged: list[ZabbixNetworkLiveSeries] = []

    for current_series in current:
        key = (
            current_series.host_id,
            current_series.metric,
            current_series.interface,
        )
        points_by_time: dict[datetime, ZabbixNetworkLivePoint] = {}
        previous_series = previous_by_key.get(key)
        if previous_series is not None:
            for point in previous_series.points:
                if point.observed_at >= cutoff:
                    points_by_time[point.observed_at] = point
        for point in current_series.points:
            if point.observed_at >= cutoff:
                points_by_time[point.observed_at] = point

        points = sorted(points_by_time.values(), key=lambda point: point.observed_at)
        points = points[-ZABBIX_LIVE_MAX_POINTS:]
        if points:
            merged.append(current_series.model_copy(update={"points": points}))

    return merged


def _merge_warnings(existing: list[str], state_warnings: list[str]) -> list[str]:
    merged: list[str] = []
    for warning in [*existing, *state_warnings]:
        if warning not in merged:
            merged.append(warning)
        if len(merged) == 20:
            break
    return merged
