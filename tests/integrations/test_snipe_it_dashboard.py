from datetime import date, datetime, timedelta, timezone

from argon2 import PasswordHasher, Type
from pydantic import SecretStr
from sqlalchemy import text

from app.db.models import SyncRun, User
from app.integrations.snipe_it.dashboard_service import (
    SnipeItAssetStoreUnavailable,
    SnipeItDashboardAssetRecord,
    SnipeItDashboardService,
    get_snipe_it_dashboard_service,
)


NOW = datetime(2026, 8, 17, 1, 0, tzinfo=timezone.utc)


class FakeAssetRepository:
    def __init__(self, assets=None, *, unavailable: bool = False) -> None:
        self.assets = list(assets or [])
        self.unavailable = unavailable

    def list_assets(self) -> list[SnipeItDashboardAssetRecord]:
        if self.unavailable:
            raise SnipeItAssetStoreUnavailable
        return list(self.assets)


def asset(asset_id: int, **overrides) -> SnipeItDashboardAssetRecord:
    values = {
        "source_asset_id": asset_id,
        "asset_tag": f"LT-{asset_id}",
        "serial": f"SERIAL-{asset_id}",
        "category": "Laptop",
        "status_label": "Ready to Deploy",
        "assigned_to_id": None,
        "location": "Main Office",
        "warranty_expires": date(2027, 8, 17),
        "synced_at": NOW - timedelta(minutes=5),
    }
    values.update(overrides)
    return SnipeItDashboardAssetRecord(**values)


def configure_snipe_it(auth_env) -> None:
    auth_env.settings.snipe_it_base_url = "https://snipe.internal"
    auth_env.settings.snipe_it_api_token = "fake-token"


def seed_sync_run(auth_env, *, status: str = "success", minutes_ago: int = 5) -> None:
    with auth_env.session_factory() as db:
        completed_at = NOW - timedelta(minutes=minutes_ago)
        db.add(
            SyncRun(
                source="snipe_it",
                sync_type="full",
                status=status,
                started_at=completed_at - timedelta(minutes=1),
                completed_at=completed_at,
                records_received=4 if status == "success" else 0,
                records_upserted=4 if status == "success" else 0,
                error_code=None if status == "success" else "SOURCE_UNAVAILABLE",
            )
        )
        db.commit()


def login(auth_env) -> None:
    with auth_env.session_factory() as db:
        db.add(
            User(
                username="alice",
                password_hash=PasswordHasher(type=Type.ID).hash("correct horse"),
                is_active=True,
                is_admin=False,
            )
        )
        db.commit()
    response = auth_env.client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "correct horse"},
    )
    assert response.status_code == 200


def test_snipe_it_dashboard_requires_authentication(auth_env) -> None:
    response = auth_env.client.get("/api/dashboard/snipe-it")
    assert response.status_code == 401


def test_snipe_it_dashboard_accepts_configured_grafana_api_token(auth_env) -> None:
    auth_env.settings.grafana_api_token = SecretStr("g" * 48)
    expected = None
    with auth_env.session_factory() as db:
        expected = SnipeItDashboardService(
            db=db,
            settings=auth_env.settings,
            asset_repository=FakeAssetRepository(),
            clock=lambda: NOW,
        ).get_dashboard()

    class FakeService:
        def get_dashboard(self):
            return expected

    auth_env.client.app.dependency_overrides[get_snipe_it_dashboard_service] = lambda: FakeService()
    try:
        response = auth_env.client.get(
            "/api/dashboard/snipe-it",
            headers={"Authorization": f"Bearer {'g' * 48}"},
        )
    finally:
        auth_env.client.app.dependency_overrides.pop(get_snipe_it_dashboard_service, None)

    assert response.status_code == 200
    assert response.json()["source"] == "snipe_it"


def test_dashboard_aggregates_normalized_assets_without_exposing_assignee_names(auth_env) -> None:
    configure_snipe_it(auth_env)
    seed_sync_run(auth_env)
    repository = FakeAssetRepository(
        [
            asset(101, assigned_to_id=10, status_label="Deployed", category="Laptop"),
            asset(
                102,
                asset_tag=None,
                serial=None,
                category="Laptop",
                status_label="Ready to Deploy",
                warranty_expires=date(2026, 8, 10),
            ),
            asset(
                103,
                category="Monitor",
                status_label="Deployed",
                assigned_to_id=11,
                location="Branch Office",
                warranty_expires=date(2026, 9, 1),
            ),
            asset(
                104,
                category=None,
                status_label=None,
                location=None,
                warranty_expires=None,
            ),
        ]
    )

    with auth_env.session_factory() as db:
        response = SnipeItDashboardService(
            db=db,
            settings=auth_env.settings,
            asset_repository=repository,
            clock=lambda: NOW,
        ).get_dashboard()

    assert response.source == "snipe_it"
    assert response.health.status == "healthy"
    assert response.is_stale is False
    assert response.summary.model_dump() == {
        "assets_total": 4,
        "assets_assigned": 2,
        "assets_unassigned": 2,
        "assets_missing_serial": 1,
        "assets_missing_asset_tag": 1,
        "warranty_expired": 1,
        "warranty_expiring_soon": 1,
    }
    assert {item.name: item.count for item in response.status_distribution} == {
        "Deployed": 2,
        "Ready to Deploy": 1,
        "Unknown": 1,
    }
    assert {item.name: item.count for item in response.category_distribution} == {
        "Laptop": 2,
        "Monitor": 1,
        "Uncategorized": 1,
    }
    assert {item.name: item.count for item in response.location_distribution} == {
        "Main Office": 2,
        "Branch Office": 1,
        "Unknown": 1,
    }
    assert "assigned_to" not in response.model_dump_json()


def test_executive_summary_uses_normalized_dashboard_metrics(auth_env) -> None:
    configure_snipe_it(auth_env)
    seed_sync_run(auth_env)
    repository = FakeAssetRepository(
        [
            asset(101, assigned_to_id=10),
            asset(102, asset_tag=None, serial=None, warranty_expires=date(2026, 8, 10)),
            asset(103, assigned_to_id=11, warranty_expires=date(2026, 9, 1)),
            asset(104, warranty_expires=None),
        ]
    )

    with auth_env.session_factory() as db:
        response = SnipeItDashboardService(
            db=db,
            settings=auth_env.settings,
            asset_repository=repository,
            clock=lambda: NOW,
        ).get_executive_summary()

    assert response.source == "snipe_it"
    assert response.observed_at == NOW
    assert response.health.source == "snipe_it"
    assert response.health.status == "healthy"
    assert response.is_stale is False
    assert response.warnings == []
    assert response.metrics == {
        "assets_total": 4,
        "assets_assigned": 2,
        "assets_unassigned": 2,
        "assets_missing_serial": 1,
        "assets_missing_asset_tag": 1,
        "warranty_expired": 1,
        "warranty_expiring_soon": 1,
    }


def test_executive_summary_preserves_stale_degraded_state(auth_env) -> None:
    configure_snipe_it(auth_env)
    seed_sync_run(auth_env, status="success", minutes_ago=10)
    seed_sync_run(auth_env, status="failed", minutes_ago=1)

    with auth_env.session_factory() as db:
        response = SnipeItDashboardService(
            db=db,
            settings=auth_env.settings,
            asset_repository=FakeAssetRepository([asset(101)]),
            clock=lambda: NOW,
        ).get_executive_summary()

    assert response.source == "snipe_it"
    assert response.is_stale is True
    assert response.health.status == "degraded"
    assert response.health.is_stale is True
    assert response.metrics["assets_total"] == 1
    assert response.warnings


def test_dashboard_marks_previous_data_stale_when_latest_sync_failed(auth_env) -> None:
    configure_snipe_it(auth_env)
    seed_sync_run(auth_env, status="success", minutes_ago=10)
    seed_sync_run(auth_env, status="failed", minutes_ago=1)

    with auth_env.session_factory() as db:
        response = SnipeItDashboardService(
            db=db,
            settings=auth_env.settings,
            asset_repository=FakeAssetRepository([asset(101)]),
            clock=lambda: NOW,
        ).get_dashboard()

    assert response.health.status == "degraded"
    assert response.health.is_stale is True
    assert response.is_stale is True
    assert response.summary.assets_total == 1
    assert response.warnings


def test_dashboard_marks_old_success_stale(auth_env) -> None:
    configure_snipe_it(auth_env)
    seed_sync_run(auth_env, status="success", minutes_ago=31)

    with auth_env.session_factory() as db:
        response = SnipeItDashboardService(
            db=db,
            settings=auth_env.settings,
            asset_repository=FakeAssetRepository([asset(101)]),
            clock=lambda: NOW,
        ).get_dashboard()

    assert response.health.status == "degraded"
    assert response.is_stale is True
    assert any("older" in warning for warning in response.warnings)


def test_unconfigured_dashboard_reports_not_configured_without_source_call(auth_env) -> None:
    with auth_env.session_factory() as db:
        response = SnipeItDashboardService(
            db=db,
            settings=auth_env.settings,
            asset_repository=FakeAssetRepository(),
            clock=lambda: NOW,
        ).get_dashboard()

    assert response.health.status == "not_configured"
    assert response.summary.assets_total == 0


def test_configured_dashboard_reports_unavailable_until_asset_store_exists(auth_env) -> None:
    configure_snipe_it(auth_env)

    with auth_env.session_factory() as db:
        response = SnipeItDashboardService(
            db=db,
            settings=auth_env.settings,
            asset_repository=FakeAssetRepository(unavailable=True),
            clock=lambda: NOW,
        ).get_dashboard()

    assert response.health.status == "unavailable"
    assert response.summary.assets_total == 0
    assert response.warnings


def test_sqlalchemy_adapter_reads_committed_asset_schema(auth_env) -> None:
    configure_snipe_it(auth_env)
    seed_sync_run(auth_env)
    with auth_env.session_factory() as db:
        db.execute(
            text(
                """
                INSERT INTO assets (
                    source_asset_id, asset_tag, serial, category, status_label,
                    assigned_to_id, location, warranty_expires, synced_at
                ) VALUES (
                    201, 'LT-201', 'SERIAL-201', 'Laptop', 'Deployed',
                    20, 'Main Office', '2026-09-01', '2026-08-17 00:55:00'
                )
                """
            )
        )
        db.commit()

        response = SnipeItDashboardService(
            db=db,
            settings=auth_env.settings,
            clock=lambda: NOW,
        ).get_dashboard()

    assert response.health.status == "healthy"
    assert response.summary.assets_total == 1
    assert response.summary.assets_assigned == 1
    assert response.summary.warranty_expiring_soon == 1
    assert response.status_distribution[0].name == "Deployed"


def test_authenticated_route_uses_dashboard_service_dependency(auth_env) -> None:
    configure_snipe_it(auth_env)
    login(auth_env)
    expected = None
    with auth_env.session_factory() as db:
        expected = SnipeItDashboardService(
            db=db,
            settings=auth_env.settings,
            asset_repository=FakeAssetRepository(),
            clock=lambda: NOW,
        ).get_dashboard()

    class FakeService:
        def get_dashboard(self):
            return expected

    auth_env.client.app.dependency_overrides[get_snipe_it_dashboard_service] = lambda: FakeService()
    try:
        response = auth_env.client.get("/api/dashboard/snipe-it")
    finally:
        auth_env.client.app.dependency_overrides.pop(get_snipe_it_dashboard_service, None)

    assert response.status_code == 200
    assert response.json()["source"] == "snipe_it"
    assert response.json()["summary"]["assets_total"] == 0
