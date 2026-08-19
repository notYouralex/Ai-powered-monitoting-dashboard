import asyncio
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher, Type
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError

from app.contracts import ExecutiveSourceSummary, IntegrationHealthSummary
from app.core.errors import IntegrationError
from app.db.models import User
from app.integrations.health.models import IntegrationHealthResponse
from app.integrations.health.router import get_integration_health_service
from app.integrations.health.service import IntegrationHealthService


NOW = datetime(2026, 8, 19, 2, 45, tzinfo=timezone.utc)
WAZUH_START = NOW - timedelta(hours=24)


def make_summary(
    source: str,
    *,
    status: str = "healthy",
    is_stale: bool = False,
    warnings: list[str] | None = None,
) -> ExecutiveSourceSummary:
    warning_values = warnings or []
    health = IntegrationHealthSummary(
        source=source,
        status=status,
        observed_at=NOW,
        last_success_at=NOW - timedelta(minutes=5) if status != "not_configured" else None,
        response_time_ms=25 if source in {"wazuh", "zabbix"} else None,
        is_stale=is_stale,
        warnings=warning_values,
    )
    return ExecutiveSourceSummary(
        source=source,
        observed_at=NOW,
        is_stale=is_stale,
        health=health,
        metrics={},
        warnings=warning_values,
    )


class FakeWazuhService:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result or make_summary("wazuh")
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
) -> IntegrationHealthService:
    return IntegrationHealthService(
        wazuh_service=wazuh or FakeWazuhService(),
        zabbix_service=zabbix or FakeSyncService(make_summary("zabbix")),
        snipe_it_service=snipe_it or FakeSyncService(make_summary("snipe_it")),
        freshservice_service=freshservice or FakeSyncService(make_summary("freshservice")),
        clock=lambda: NOW,
    )


def test_health_service_aggregates_existing_normalized_health() -> None:
    async def run() -> None:
        wazuh = FakeWazuhService()
        zabbix = FakeSyncService(
            make_summary(
                "zabbix",
                status="degraded",
                is_stale=True,
                warnings=["Zabbix cached data is stale."],
            )
        )
        snipe_it = FakeSyncService(make_summary("snipe_it", status="not_configured"))
        freshservice = FakeSyncService(make_summary("freshservice", status="unavailable"))
        service = make_service(
            wazuh=wazuh,
            zabbix=zabbix,
            snipe_it=snipe_it,
            freshservice=freshservice,
        )

        response = await service.get_health()

        assert response.observed_at == NOW
        assert [item.source for item in response.integrations] == [
            "wazuh",
            "zabbix",
            "snipe_it",
            "freshservice",
        ]
        assert [item.status for item in response.integrations] == [
            "healthy",
            "degraded",
            "not_configured",
            "unavailable",
        ]
        assert response.integrations[1].is_stale is True
        assert response.integrations[1].warnings == ["Zabbix cached data is stale."]
        assert response.integrations[0].response_time_ms == 25
        assert wazuh.calls == [(WAZUH_START, NOW)]
        assert zabbix.calls == snipe_it.calls == freshservice.calls == 1

    asyncio.run(run())


def test_health_service_isolates_expected_source_failures() -> None:
    async def run() -> None:
        zabbix = FakeSyncService(
            make_summary("zabbix"),
            error=IntegrationError(
                source="zabbix",
                code="SOURCE_UNAVAILABLE",
                retryable=True,
            ),
        )
        response = await make_service(zabbix=zabbix).get_health()

        by_source = {item.source: item for item in response.integrations}
        assert by_source["zabbix"].status == "unavailable"
        assert by_source["zabbix"].warnings == ["Zabbix health is unavailable."]
        assert by_source["wazuh"].status == "healthy"
        assert by_source["snipe_it"].status == "healthy"
        assert by_source["freshservice"].status == "healthy"

    asyncio.run(run())


def test_health_service_preserves_not_configured_source() -> None:
    async def run() -> None:
        wazuh = FakeWazuhService(
            error=IntegrationError(
                source="wazuh",
                code="SOURCE_NOT_CONFIGURED",
                retryable=False,
            )
        )
        response = await make_service(wazuh=wazuh).get_health()

        by_source = {item.source: item for item in response.integrations}
        assert by_source["wazuh"].status == "not_configured"
        assert by_source["wazuh"].warnings == ["Wazuh is not configured."]
        assert by_source["zabbix"].status == "healthy"

    asyncio.run(run())


def test_health_service_isolates_local_database_failure() -> None:
    async def run() -> None:
        freshservice = FakeSyncService(
            make_summary("freshservice"),
            error=SQLAlchemyError("database unavailable"),
        )
        response = await make_service(freshservice=freshservice).get_health()

        by_source = {item.source: item for item in response.integrations}
        assert by_source["freshservice"].status == "unavailable"
        assert by_source["freshservice"].warnings == ["Freshservice health is unavailable."]
        assert by_source["zabbix"].status == "healthy"

    asyncio.run(run())


def create_user(auth_env) -> None:
    with auth_env.session_factory() as db:
        db.add(
            User(
                username="integration-health-user",
                password_hash=PasswordHasher(type=Type.ID).hash("correct horse"),
                is_active=True,
                is_admin=False,
            )
        )
        db.commit()


def login(auth_env) -> None:
    response = auth_env.client.post(
        "/api/auth/login",
        json={"username": "integration-health-user", "password": "correct horse"},
    )
    assert response.status_code == 200


class FakeIntegrationHealthService:
    def __init__(self) -> None:
        self.calls = 0

    async def get_health(self) -> IntegrationHealthResponse:
        self.calls += 1
        return IntegrationHealthResponse(
            observed_at=NOW,
            integrations=[
                make_summary("wazuh").health,
                make_summary("zabbix", status="degraded", is_stale=True).health,
                make_summary("snipe_it").health,
                make_summary("freshservice").health,
            ],
        )


def test_integration_health_requires_authentication(auth_env) -> None:
    response = auth_env.client.get("/api/integrations/health")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_integration_health_reports_unconfigured_wazuh_without_breaking_endpoint(auth_env) -> None:
    create_user(auth_env)
    login(auth_env)

    response = auth_env.client.get("/api/integrations/health")

    assert response.status_code == 200
    by_source = {item["source"]: item for item in response.json()["integrations"]}
    assert by_source["wazuh"]["status"] == "not_configured"
    assert by_source["wazuh"]["warnings"] == ["Wazuh is not configured."]
    assert set(by_source) == {"wazuh", "zabbix", "snipe_it", "freshservice"}


def test_integration_health_returns_aggregated_response(auth_env) -> None:
    create_user(auth_env)
    login(auth_env)
    fake_service = FakeIntegrationHealthService()
    auth_env.client.app.dependency_overrides[get_integration_health_service] = lambda: fake_service

    response = auth_env.client.get("/api/integrations/health")

    assert response.status_code == 200
    assert response.json()["observed_at"] == "2026-08-19T02:45:00Z"
    assert [item["source"] for item in response.json()["integrations"]] == [
        "wazuh",
        "zabbix",
        "snipe_it",
        "freshservice",
    ]
    assert response.json()["integrations"][1]["status"] == "degraded"
    assert response.json()["integrations"][1]["is_stale"] is True
    assert fake_service.calls == 1


def test_integration_health_accepts_grafana_bearer_token(auth_env) -> None:
    token = "g" * 48
    auth_env.settings.grafana_api_token = SecretStr(token)
    fake_service = FakeIntegrationHealthService()
    auth_env.client.app.dependency_overrides[get_integration_health_service] = lambda: fake_service

    response = auth_env.client.get(
        "/api/integrations/health",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert fake_service.calls == 1
