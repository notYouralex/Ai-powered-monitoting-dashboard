import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts import IntegrationHealthSummary
from app.core.config import Settings
from app.core.errors import IntegrationError
from app.db.base import Base
from app.db.models import SyncRun, ZabbixDashboardCache
from app.db.session import create_engine_for_url
from app.integrations.zabbix.cache import (
    ZabbixCacheRefreshService,
    ZabbixCachedDashboardService,
)
from app.integrations.zabbix.models import (
    ZabbixDashboardResponse,
    ZabbixDashboardSummary,
    ZabbixHost,
    ZabbixResourcePressure,
)


T0 = datetime(2026, 8, 14, 1, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(seconds=1)
T2 = T0 + timedelta(minutes=1)
T3 = T2 + timedelta(seconds=1)


def make_db() -> Session:
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def host(host_id: str) -> ZabbixHost:
    return ZabbixHost(
        host_id=host_id,
        technical_name=f"host-{host_id}",
        name=f"Host {host_id}",
        enabled=True,
        in_maintenance=False,
        interfaces=[],
    )


class FakeZabbixClient:
    def __init__(self) -> None:
        self.hosts = [host("1")]
        self.resource_pressure: list[ZabbixResourcePressure] | None = None
        self.error: IntegrationError | None = None

    async def list_hosts(self):
        if self.error is not None:
            raise self.error
        return self.hosts

    async def list_active_problems(self):
        return []

    async def list_resource_pressure(self):
        if self.resource_pressure is not None:
            return self.resource_pressure
        return [ZabbixResourcePressure(host_id=row.host_id) for row in self.hosts]

    async def list_resource_trends(self, host_ids: list[str]):
        return []

    async def list_topology_maps(self):
        return []


def test_refresh_creates_normalized_singleton_snapshot_and_success_run() -> None:
    async def run() -> None:
        db = make_db()
        client = FakeZabbixClient()
        clock_values = iter([T0, T1])
        service = ZabbixCacheRefreshService(client, clock=lambda: next(clock_values))

        result = await service.refresh(db)

        cached = db.get(ZabbixDashboardCache, 1)
        assert cached is not None
        assert cached.refreshed_at == T1
        assert cached.snapshot["source"] == "zabbix"
        assert cached.snapshot["summary"]["hosts_total"] == 1
        assert result.source == "zabbix"
        assert result.sync_type == "snapshot"
        assert result.status == "success"
        assert result.completed_at == T1
        assert result.records_received == 1
        assert result.records_upserted == 1
        db.close()

    asyncio.run(run())


def test_refresh_replaces_singleton_snapshot_without_adding_cache_rows() -> None:
    async def run() -> None:
        db = make_db()
        client = FakeZabbixClient()
        clock_values = iter([T0, T1, T2, T3])
        service = ZabbixCacheRefreshService(client, clock=lambda: next(clock_values))

        await service.refresh(db)
        client.hosts = [host("1"), host("2")]
        await service.refresh(db)

        cached = db.get(ZabbixDashboardCache, 1)
        assert cached is not None
        assert cached.snapshot["summary"]["hosts_total"] == 2
        assert cached.refreshed_at == T3
        assert db.scalar(select(func.count()).select_from(ZabbixDashboardCache)) == 1
        assert db.scalar(select(func.count()).select_from(SyncRun).where(SyncRun.source == "zabbix")) == 2
        db.close()

    asyncio.run(run())


def test_refresh_accumulates_live_cpu_and_memory_samples_in_singleton_cache() -> None:
    async def run() -> None:
        db = make_db()
        client = FakeZabbixClient()
        client.resource_pressure = [
            ZabbixResourcePressure(
                host_id="1",
                cpu_used_percent=20,
                cpu_observed_at=T0,
                memory_used_percent=40,
                memory_observed_at=T0,
            )
        ]
        clock_values = iter([T0, T1, T2, T3])
        service = ZabbixCacheRefreshService(client, clock=lambda: next(clock_values))

        await service.refresh(db)
        client.resource_pressure = [
            ZabbixResourcePressure(
                host_id="1",
                cpu_used_percent=30,
                cpu_observed_at=T2,
                memory_used_percent=50,
                memory_observed_at=T2,
            )
        ]
        await service.refresh(db)

        cached = db.get(ZabbixDashboardCache, 1)
        assert cached is not None
        live = cached.snapshot["resource_live"]
        assert [(row["host_id"], row["metric"]) for row in live] == [
            ("1", "cpu"),
            ("1", "memory"),
        ]
        assert live[0]["points"] == [
            {"observed_at": T0.isoformat().replace("+00:00", "Z"), "used_percent": 20.0},
            {"observed_at": T2.isoformat().replace("+00:00", "Z"), "used_percent": 30.0},
        ]
        assert live[1]["points"] == [
            {"observed_at": T0.isoformat().replace("+00:00", "Z"), "used_percent": 40.0},
            {"observed_at": T2.isoformat().replace("+00:00", "Z"), "used_percent": 50.0},
        ]
        db.close()

    asyncio.run(run())


def test_refresh_prunes_live_resource_samples_older_than_one_hour() -> None:
    async def run() -> None:
        db = make_db()
        client = FakeZabbixClient()
        client.resource_pressure = [
            ZabbixResourcePressure(
                host_id="1",
                cpu_used_percent=20,
                cpu_observed_at=T0,
            )
        ]
        later = T0 + timedelta(minutes=61)
        clock_values = iter([T0, T1, later, later + timedelta(seconds=1)])
        service = ZabbixCacheRefreshService(client, clock=lambda: next(clock_values))

        await service.refresh(db)
        client.resource_pressure = [
            ZabbixResourcePressure(
                host_id="1",
                cpu_used_percent=30,
                cpu_observed_at=later,
            )
        ]
        await service.refresh(db)

        cached = db.get(ZabbixDashboardCache, 1)
        assert cached is not None
        assert cached.snapshot["resource_live"][0]["points"] == [
            {"observed_at": later.isoformat().replace("+00:00", "Z"), "used_percent": 30.0}
        ]
        db.close()

    asyncio.run(run())


def test_failed_refresh_preserves_last_successful_snapshot_and_records_safe_error() -> None:
    async def run() -> None:
        db = make_db()
        client = FakeZabbixClient()
        clock_values = iter([T0, T1, T2, T3])
        service = ZabbixCacheRefreshService(client, clock=lambda: next(clock_values))
        await service.refresh(db)
        cached = db.get(ZabbixDashboardCache, 1)
        assert cached is not None
        snapshot_before = deepcopy(cached.snapshot)
        refreshed_before = cached.refreshed_at

        client.error = IntegrationError(
            source="zabbix",
            code="SOURCE_UNAVAILABLE",
            retryable=True,
        )
        with pytest.raises(IntegrationError) as exc_info:
            await service.refresh(db)

        db.expire_all()
        cached_after = db.get(ZabbixDashboardCache, 1)
        latest_run = db.scalar(
            select(SyncRun)
            .where(SyncRun.source == "zabbix")
            .order_by(SyncRun.id.desc())
            .limit(1)
        )
        assert exc_info.value is client.error
        assert cached_after is not None
        assert cached_after.snapshot == snapshot_before
        assert cached_after.refreshed_at == refreshed_before
        assert latest_run is not None
        assert latest_run.status == "failed"
        assert latest_run.error_code == "SOURCE_UNAVAILABLE"
        assert latest_run.records_upserted == 0
        db.close()

    asyncio.run(run())


def test_database_failure_during_refresh_preserves_previous_snapshot(monkeypatch) -> None:
    async def run() -> None:
        db = make_db()
        client = FakeZabbixClient()
        clock_values = iter([T0, T1, T2, T3, T3 + timedelta(seconds=1)])
        service = ZabbixCacheRefreshService(client, clock=lambda: next(clock_values))
        await service.refresh(db)
        cached = db.get(ZabbixDashboardCache, 1)
        assert cached is not None
        snapshot_before = deepcopy(cached.snapshot)
        refreshed_before = cached.refreshed_at
        client.hosts = [host("1"), host("2")]

        original_commit = db.commit
        commit_calls = 0

        def flaky_commit() -> None:
            nonlocal commit_calls
            commit_calls += 1
            if commit_calls == 2:
                from sqlalchemy.exc import SQLAlchemyError

                raise SQLAlchemyError("forced cache persistence failure")
            original_commit()

        monkeypatch.setattr(db, "commit", flaky_commit)

        from sqlalchemy.exc import SQLAlchemyError

        with pytest.raises(SQLAlchemyError):
            await service.refresh(db)

        db.expire_all()
        cached_after = db.get(ZabbixDashboardCache, 1)
        latest_run = db.scalar(
            select(SyncRun)
            .where(SyncRun.source == "zabbix")
            .order_by(SyncRun.id.desc())
            .limit(1)
        )
        assert cached_after is not None
        assert cached_after.snapshot == snapshot_before
        assert cached_after.refreshed_at == refreshed_before
        assert latest_run is not None
        assert latest_run.status == "failed"
        assert latest_run.error_code == "SYNC_DATABASE_ERROR"
        assert commit_calls == 3
        db.close()

    asyncio.run(run())


def make_settings(*, configured: bool) -> Settings:
    values = {
        "app_env": "test",
        "app_secret_key": "t" * 48,
        "database_url": "sqlite:///:memory:",
        "_env_file": None,
    }
    if configured:
        values.update(
            zabbix_base_url="https://zabbix.example/api_jsonrpc.php",
            zabbix_api_token="test-token",
        )
    return Settings(**values)


def dashboard_snapshot(*, observed_at: datetime = T0) -> dict:
    summary = ZabbixDashboardSummary(
        hosts_total=1,
        hosts_enabled=1,
        hosts_disabled=0,
        hosts_in_maintenance=0,
        interfaces_available=0,
        interfaces_unavailable=0,
        interfaces_unknown=0,
        problems_total=0,
        problems_not_classified=0,
        problems_information=0,
        problems_warning=0,
        problems_average=0,
        problems_high=0,
        problems_disaster=0,
        problems_unknown=0,
        problems_unacknowledged=0,
        problems_suppressed=0,
        resource_hosts_total=0,
        resource_hosts_with_cpu=0,
        resource_hosts_with_memory=0,
        resource_hosts_with_disk=0,
    )
    response = ZabbixDashboardResponse(
        observed_at=observed_at,
        health=IntegrationHealthSummary(
            source="zabbix",
            status="healthy",
            observed_at=observed_at,
            last_success_at=observed_at,
            response_time_ms=12,
            is_stale=False,
            warnings=[],
        ),
        summary=summary,
        warnings=["Existing normalized warning."],
    )
    return response.model_dump(mode="json")


def seed_cache(
    db: Session,
    *,
    refreshed_at: datetime = T0,
    latest_status: str = "success",
    latest_at: datetime | None = None,
) -> None:
    db.add(
        ZabbixDashboardCache(
            id=1,
            snapshot=dashboard_snapshot(observed_at=refreshed_at),
            refreshed_at=refreshed_at,
        )
    )
    db.add(
        SyncRun(
            source="zabbix",
            sync_type="snapshot",
            status="success",
            started_at=refreshed_at - timedelta(seconds=1),
            completed_at=refreshed_at,
            records_received=1,
            records_upserted=1,
        )
    )
    if latest_status == "failed":
        failed_at = latest_at or refreshed_at + timedelta(seconds=60)
        db.add(
            SyncRun(
                source="zabbix",
                sync_type="snapshot",
                status="failed",
                started_at=failed_at,
                completed_at=failed_at + timedelta(seconds=1),
                records_received=0,
                records_upserted=0,
                error_code="SOURCE_UNAVAILABLE",
            )
        )
    db.commit()


def test_cached_dashboard_is_healthy_within_refresh_window() -> None:
    db = make_db()
    seed_cache(db)
    now = T0 + timedelta(seconds=60)

    response = ZabbixCachedDashboardService(
        db,
        make_settings(configured=True),
        clock=lambda: now,
    ).get_dashboard()

    assert response.observed_at == T0
    assert response.is_stale is False
    assert response.health.status == "healthy"
    assert response.health.observed_at == now
    assert response.health.last_success_at == T0
    assert response.health.response_time_ms == 12
    assert response.health.warnings == []
    assert response.warnings == ["Existing normalized warning."]
    db.close()


def test_cached_dashboard_marks_latest_failed_refresh_degraded_and_stale() -> None:
    db = make_db()
    seed_cache(db, latest_status="failed", latest_at=T0 + timedelta(seconds=60))
    now = T0 + timedelta(seconds=70)

    response = ZabbixCachedDashboardService(
        db,
        make_settings(configured=True),
        clock=lambda: now,
    ).get_dashboard()

    warning = "The latest Zabbix refresh failed; showing last successful cached data."
    assert response.is_stale is True
    assert response.health.status == "degraded"
    assert response.health.is_stale is True
    assert response.health.warnings == [warning]
    assert response.warnings == ["Existing normalized warning.", warning]
    db.close()


def test_cached_dashboard_marks_old_snapshot_degraded_and_stale() -> None:
    db = make_db()
    seed_cache(db)
    now = T0 + timedelta(seconds=121)

    response = ZabbixCachedDashboardService(
        db,
        make_settings(configured=True),
        clock=lambda: now,
    ).get_dashboard()

    warning = "Zabbix cached data is older than the expected refresh window."
    assert response.is_stale is True
    assert response.health.status == "degraded"
    assert response.health.warnings == [warning]
    assert response.warnings == ["Existing normalized warning.", warning]
    db.close()


def test_cached_dashboard_keeps_previous_data_when_zabbix_becomes_unconfigured() -> None:
    db = make_db()
    seed_cache(db)
    now = T0 + timedelta(seconds=10)

    response = ZabbixCachedDashboardService(
        db,
        make_settings(configured=False),
        clock=lambda: now,
    ).get_dashboard()

    warning = "Zabbix is not configured; showing previously cached data."
    assert response.is_stale is True
    assert response.health.status == "not_configured"
    assert response.health.warnings == [warning]
    assert response.warnings == ["Existing normalized warning.", warning]
    db.close()


@pytest.mark.parametrize(
    ("configured", "code", "retryable"),
    [
        (True, "SOURCE_UNAVAILABLE", True),
        (False, "SOURCE_NOT_CONFIGURED", False),
    ],
)
def test_cached_dashboard_without_successful_snapshot_returns_safe_source_error(
    configured: bool,
    code: str,
    retryable: bool,
) -> None:
    db = make_db()
    service = ZabbixCachedDashboardService(
        db,
        make_settings(configured=configured),
        clock=lambda: T0,
    )

    with pytest.raises(IntegrationError) as exc_info:
        service.get_dashboard()

    assert exc_info.value.source == "zabbix"
    assert exc_info.value.code == code
    assert exc_info.value.retryable is retryable
    db.close()


def test_cached_dashboard_builds_normalized_executive_summary() -> None:
    db = make_db()
    seed_cache(db)
    cached = db.get(ZabbixDashboardCache, 1)
    assert cached is not None
    snapshot = deepcopy(cached.snapshot)
    snapshot["summary"].update(
        {
            "hosts_total": 12,
            "hosts_enabled": 11,
            "hosts_disabled": 1,
            "hosts_in_maintenance": 2,
            "interfaces_available": 10,
            "interfaces_unavailable": 2,
            "interfaces_unknown": 1,
            "problems_total": 7,
            "problems_high": 2,
            "problems_disaster": 1,
            "problems_unacknowledged": 4,
            "resource_hosts_total": 9,
            "resource_hosts_with_cpu": 8,
            "resource_hosts_with_memory": 7,
            "resource_hosts_with_disk": 6,
        }
    )
    cached.snapshot = snapshot
    db.commit()
    now = T0 + timedelta(seconds=60)

    response = ZabbixCachedDashboardService(
        db,
        make_settings(configured=True),
        clock=lambda: now,
    ).get_executive_summary()

    assert response.source == "zabbix"
    assert response.observed_at == T0
    assert response.health.source == "zabbix"
    assert response.health.status == "healthy"
    assert response.is_stale is False
    assert response.warnings == ["Existing normalized warning."]
    assert response.metrics == {
        "hosts_total": 12,
        "hosts_enabled": 11,
        "hosts_disabled": 1,
        "hosts_in_maintenance": 2,
        "interfaces_unavailable": 2,
        "problems_total": 7,
        "problems_high": 2,
        "problems_disaster": 1,
        "problems_unacknowledged": 4,
        "resource_hosts_total": 9,
        "resource_hosts_with_cpu": 8,
        "resource_hosts_with_memory": 7,
        "resource_hosts_with_disk": 6,
    }
    db.close()


def test_cached_executive_summary_preserves_degraded_stale_state() -> None:
    db = make_db()
    seed_cache(db, latest_status="failed", latest_at=T0 + timedelta(seconds=60))
    now = T0 + timedelta(seconds=70)

    response = ZabbixCachedDashboardService(
        db,
        make_settings(configured=True),
        clock=lambda: now,
    ).get_executive_summary()

    warning = "The latest Zabbix refresh failed; showing last successful cached data."
    assert response.source == "zabbix"
    assert response.is_stale is True
    assert response.health.status == "degraded"
    assert response.health.is_stale is True
    assert response.health.warnings == [warning]
    assert response.warnings == ["Existing normalized warning.", warning]
    db.close()
