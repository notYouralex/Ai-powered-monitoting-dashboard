import asyncio
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher, Type
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError

from app.contracts import ExecutiveSourceSummary, IntegrationHealthSummary
from app.core.errors import IntegrationError
from app.db.models import User
from app.dashboard.executive.models import ExecutiveDashboardResponse
from app.dashboard.executive.router import get_executive_dashboard_service
from app.dashboard.executive.service import ExecutiveDashboardService


NOW = datetime(2026, 8, 18, 3, 30, tzinfo=timezone.utc)
START = NOW - timedelta(hours=24)


def make_summary(
    source: str,
    *,
    status: str = "healthy",
    is_stale: bool = False,
    metrics: dict | None = None,
    warnings: list[str] | None = None,
) -> ExecutiveSourceSummary:
    warning_values = warnings or []
    health = IntegrationHealthSummary(
        source=source,
        status=status,
        observed_at=NOW,
        last_success_at=NOW if status != "not_configured" else None,
        is_stale=is_stale,
        warnings=warning_values,
    )
    return ExecutiveSourceSummary(
        source=source,
        observed_at=NOW,
        is_stale=is_stale,
        health=health,
        metrics=metrics or {},
        warnings=warning_values,
    )


class FakeWazuhService:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result or make_summary("wazuh", metrics={"alerts_critical": 2})
        self.error = error
        self.calls: list[tuple[datetime, datetime]] = []

    async def get_executive_summary(
        self,
        start: datetime,
        end: datetime,
    ) -> ExecutiveSourceSummary:
        self.calls.append((start, end))
        if self.error is not None:
            raise self.error
        return self.result


class FakeSyncService:
    def __init__(self, result: ExecutiveSourceSummary, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    def get_executive_summary(self) -> ExecutiveSourceSummary:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


def make_service(
    *,
    wazuh: FakeWazuhService | None = None,
    zabbix: FakeSyncService | None = None,
    snipe_it: FakeSyncService | None = None,
    freshservice: FakeSyncService | None = None,
) -> ExecutiveDashboardService:
    return ExecutiveDashboardService(
        wazuh_service=wazuh or FakeWazuhService(),
        zabbix_service=zabbix
        or FakeSyncService(make_summary("zabbix", metrics={"hosts_total": 12})),
        snipe_it_service=snipe_it
        or FakeSyncService(make_summary("snipe_it", metrics={"assets_total": 700})),
        freshservice_service=freshservice
        or FakeSyncService(make_summary("freshservice", metrics={"tickets_open": 14})),
        clock=lambda: NOW,
    )


def test_executive_service_combines_four_normalized_source_summaries() -> None:
    async def run() -> None:
        wazuh = FakeWazuhService()
        zabbix = FakeSyncService(make_summary("zabbix", metrics={"hosts_total": 12}))
        snipe_it = FakeSyncService(make_summary("snipe_it", metrics={"assets_total": 700}))
        freshservice = FakeSyncService(
            make_summary(
                "freshservice",
                status="degraded",
                is_stale=True,
                metrics={"tickets_open": 14},
                warnings=["Ticket data is stale."],
            )
        )
        service = make_service(
            wazuh=wazuh,
            zabbix=zabbix,
            snipe_it=snipe_it,
            freshservice=freshservice,
        )

        response = await service.get_dashboard(START, NOW)

        assert response.observed_at == NOW
        assert response.range_start == START
        assert response.range_end == NOW
        assert [item.source for item in response.sources] == [
            "wazuh",
            "zabbix",
            "snipe_it",
            "freshservice",
        ]
        assert response.sources[0].metrics["alerts_critical"] == 2
        assert response.sources[3].health.status == "degraded"
        assert response.sources[3].is_stale is True
        assert wazuh.calls == [(START, NOW)]
        assert zabbix.calls == snipe_it.calls == freshservice.calls == 1

    asyncio.run(run())


def test_executive_service_builds_render_ready_summary_fields() -> None:
    async def run() -> None:
        service = make_service(
            wazuh=FakeWazuhService(
                result=make_summary(
                    "wazuh",
                    metrics={"alerts_high": 3, "alerts_critical": 2},
                )
            ),
            zabbix=FakeSyncService(
                make_summary(
                    "zabbix",
                    status="degraded",
                    metrics={
                        "problems_high": 4,
                        "problems_disaster": 1,
                        "interfaces_unavailable": 2,
                    },
                )
            ),
            snipe_it=FakeSyncService(
                make_summary(
                    "snipe_it",
                    status="unavailable",
                    metrics={"assets_total": 700, "warranty_expired": 249},
                )
            ),
            freshservice=FakeSyncService(
                make_summary(
                    "freshservice",
                    metrics={
                        "tickets_open": 14,
                        "tickets_pending": 10,
                        "high_priority_open": 3,
                        "overdue_open": 4,
                        "resolution_sla_compliance_percent": 75.2,
                    },
                )
            ),
        )

        response = await service.get_dashboard(START, NOW)

        assert response.summary.model_dump() == {
            "overall_health_percent": 50,
            "active_alerts": 10,
            "security_alerts": 5,
            "tickets_open": 14,
            "overdue_open": 4,
            "resolution_sla_compliance_percent": 75.2,
            "assets_total": 700,
        }
        assert [item.model_dump() for item in response.health_distribution] == [
            {"name": "Healthy", "count": 2},
            {"name": "Degraded", "count": 1},
            {"name": "Unavailable", "count": 1},
            {"name": "Not configured", "count": 0},
        ]
        assert [item.model_dump() for item in response.alert_category_distribution] == [
            {"name": "Security", "count": 5},
            {"name": "Infrastructure", "count": 5},
        ]
        assert [item.model_dump() for item in response.ticket_status_distribution] == [
            {"name": "Open", "count": 14},
            {"name": "Pending", "count": 10},
        ]
        assert [item.model_dump() for item in response.attention_required] == [
            {"source": "Wazuh", "issue": "Critical Security Alerts", "count": 2},
            {"source": "Zabbix", "issue": "Disaster Problems", "count": 1},
            {"source": "Zabbix", "issue": "Unavailable Interfaces", "count": 2},
            {
                "source": "Freshservice",
                "issue": "High-Priority Open Tickets",
                "count": 3,
            },
            {"source": "Freshservice", "issue": "Overdue Tickets", "count": 4},
            {"source": "Snipe-IT", "issue": "Expired Warranties", "count": 249},
        ]

    asyncio.run(run())


def test_executive_service_preserves_empty_source_without_hiding_other_summaries() -> None:
    async def run() -> None:
        snipe_it = FakeSyncService(make_summary("snipe_it"))
        response = await make_service(snipe_it=snipe_it).get_dashboard(START, NOW)

        by_source = {item.source: item for item in response.sources}
        assert by_source["snipe_it"].metrics == {}
        assert by_source["snipe_it"].health.status == "healthy"
        assert by_source["wazuh"].metrics["alerts_critical"] == 2
        assert by_source["freshservice"].metrics["tickets_open"] == 14

    asyncio.run(run())


def test_executive_service_isolates_expected_source_failure() -> None:
    async def run() -> None:
        zabbix = FakeSyncService(
            make_summary("zabbix"),
            error=IntegrationError(source="zabbix", code="SOURCE_UNAVAILABLE", retryable=True),
        )
        service = make_service(zabbix=zabbix)

        response = await service.get_dashboard(START, NOW)

        by_source = {item.source: item for item in response.sources}
        assert by_source["zabbix"].health.status == "unavailable"
        assert by_source["zabbix"].metrics == {}
        assert by_source["zabbix"].warnings == ["Zabbix Executive summary is unavailable."]
        assert by_source["wazuh"].health.status == "healthy"
        assert by_source["snipe_it"].health.status == "healthy"
        assert by_source["freshservice"].health.status == "healthy"

    asyncio.run(run())


def test_executive_service_preserves_not_configured_without_failing_other_sources() -> None:
    async def run() -> None:
        wazuh = FakeWazuhService(
            error=IntegrationError(
                source="wazuh",
                code="SOURCE_NOT_CONFIGURED",
                retryable=False,
            )
        )
        response = await make_service(wazuh=wazuh).get_dashboard(START, NOW)

        by_source = {item.source: item for item in response.sources}
        assert by_source["wazuh"].health.status == "not_configured"
        assert by_source["wazuh"].warnings == ["Wazuh is not configured."]
        assert by_source["zabbix"].metrics["hosts_total"] == 12

    asyncio.run(run())


def test_executive_service_isolates_local_database_read_failure() -> None:
    async def run() -> None:
        freshservice = FakeSyncService(
            make_summary("freshservice"),
            error=SQLAlchemyError("database unavailable"),
        )
        response = await make_service(freshservice=freshservice).get_dashboard(START, NOW)

        by_source = {item.source: item for item in response.sources}
        assert by_source["freshservice"].health.status == "unavailable"
        assert by_source["freshservice"].metrics == {}
        assert by_source["freshservice"].warnings == [
            "Freshservice Executive summary is unavailable."
        ]
        assert by_source["zabbix"].health.status == "healthy"

    asyncio.run(run())


def create_user(auth_env) -> None:
    with auth_env.session_factory() as db:
        db.add(
            User(
                username="executive-user",
                password_hash=PasswordHasher(type=Type.ID).hash("correct horse"),
                is_active=True,
                is_admin=False,
            )
        )
        db.commit()


def login(auth_env) -> None:
    response = auth_env.client.post(
        "/api/auth/login",
        json={"username": "executive-user", "password": "correct horse"},
    )
    assert response.status_code == 200


class FakeExecutiveService:
    def __init__(self) -> None:
        self.calls: list[tuple[datetime, datetime]] = []

    async def get_dashboard(
        self,
        start: datetime,
        end: datetime,
    ) -> ExecutiveDashboardResponse:
        self.calls.append((start, end))
        return ExecutiveDashboardResponse(
            observed_at=NOW,
            range_start=start,
            range_end=end,
            sources=[
                make_summary("wazuh"),
                make_summary("zabbix"),
                make_summary("snipe_it"),
                make_summary("freshservice"),
            ],
        )


def test_executive_dashboard_requires_authentication(auth_env) -> None:
    response = auth_env.client.get("/api/dashboard/executive")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_executive_dashboard_returns_aggregated_response(auth_env) -> None:
    create_user(auth_env)
    login(auth_env)
    fake_service = FakeExecutiveService()
    auth_env.client.app.dependency_overrides[get_executive_dashboard_service] = lambda: fake_service

    response = auth_env.client.get(
        "/api/dashboard/executive",
        params={
            "from": "2026-08-17T03:30:00Z",
            "to": "2026-08-18T03:30:00Z",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["source"] for item in body["sources"]] == [
        "wazuh",
        "zabbix",
        "snipe_it",
        "freshservice",
    ]
    assert fake_service.calls == [(START, NOW)]


def test_executive_dashboard_accepts_grafana_bearer_token(auth_env) -> None:
    token = "g" * 48
    auth_env.settings.grafana_api_token = SecretStr(token)
    fake_service = FakeExecutiveService()
    auth_env.client.app.dependency_overrides[get_executive_dashboard_service] = lambda: fake_service

    response = auth_env.client.get(
        "/api/dashboard/executive",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "from": "2026-08-17T03:30:00Z",
            "to": "2026-08-18T03:30:00Z",
        },
    )

    assert response.status_code == 200
    assert fake_service.calls == [(START, NOW)]


def test_executive_dashboard_rejects_invalid_time_ranges(auth_env) -> None:
    create_user(auth_env)
    login(auth_env)
    fake_service = FakeExecutiveService()
    auth_env.client.app.dependency_overrides[get_executive_dashboard_service] = lambda: fake_service

    reversed_range = auth_env.client.get(
        "/api/dashboard/executive",
        params={
            "from": "2026-08-18T03:30:00Z",
            "to": "2026-08-17T03:30:00Z",
        },
    )
    too_large = auth_env.client.get(
        "/api/dashboard/executive",
        params={
            "from": "2026-07-01T00:00:00Z",
            "to": "2026-08-18T00:00:00Z",
        },
    )
    naive_time = auth_env.client.get(
        "/api/dashboard/executive",
        params={
            "from": "2026-08-17T03:30:00",
            "to": "2026-08-18T03:30:00",
        },
    )

    assert reversed_range.status_code == 422
    assert too_large.status_code == 422
    assert naive_time.status_code == 422
    assert fake_service.calls == []


def test_executive_dashboard_defaults_to_last_24_hours(auth_env, monkeypatch) -> None:
    create_user(auth_env)
    login(auth_env)
    fake_service = FakeExecutiveService()
    auth_env.client.app.dependency_overrides[get_executive_dashboard_service] = lambda: fake_service

    class FrozenDateTime:
        @classmethod
        def now(cls, tz):
            return NOW

    monkeypatch.setattr("app.dashboard.executive.router.datetime", FrozenDateTime)
    response = auth_env.client.get("/api/dashboard/executive")

    assert response.status_code == 200
    assert fake_service.calls == [(START, NOW)]
