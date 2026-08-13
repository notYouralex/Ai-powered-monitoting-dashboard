from datetime import datetime, timezone

from argon2 import PasswordHasher, Type

from app.contracts import IntegrationHealthSummary
from app.db.models import User
from app.integrations.zabbix import router as zabbix_router_module
from app.integrations.zabbix.models import (
    ZabbixDashboardResponse,
    ZabbixDashboardSummary,
)
from app.main import create_app


NOW = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)


def create_user(auth_env) -> None:
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


def login(auth_env) -> None:
    response = auth_env.client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "correct horse"},
    )
    assert response.status_code == 200


class FakeDashboardService:
    def __init__(self) -> None:
        self.calls = 0

    async def get_dashboard(self) -> ZabbixDashboardResponse:
        self.calls += 1
        return ZabbixDashboardResponse(
            observed_at=NOW,
            health=IntegrationHealthSummary(
                source="zabbix",
                status="healthy",
                observed_at=NOW,
                last_success_at=NOW,
                response_time_ms=1,
            ),
            summary=ZabbixDashboardSummary(
                hosts_total=0,
                hosts_enabled=0,
                hosts_disabled=0,
                hosts_in_maintenance=0,
                interfaces_available=0,
                interfaces_unavailable=0,
                interfaces_unknown=0,
            ),
        )


def test_zabbix_dashboard_requires_authentication(auth_env) -> None:
    response = auth_env.client.get("/api/dashboard/zabbix")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_authenticated_unconfigured_zabbix_returns_safe_source_error(auth_env) -> None:
    create_user(auth_env)
    login(auth_env)

    response = auth_env.client.get("/api/dashboard/zabbix")

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "SOURCE_NOT_CONFIGURED"
    assert body["error"]["source"] == "zabbix"
    assert body["error"]["retryable"] is False
    assert body["error"]["request_id"]
    assert response.headers["X-Request-ID"] == body["error"]["request_id"]


def test_authenticated_zabbix_dashboard_returns_normalized_response(auth_env) -> None:
    create_user(auth_env)
    login(auth_env)
    dependency = getattr(zabbix_router_module, "get_zabbix_dashboard_service", None)
    assert dependency is not None
    fake_service = FakeDashboardService()
    auth_env.client.app.dependency_overrides[dependency] = lambda: fake_service

    response = auth_env.client.get("/api/dashboard/zabbix")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "zabbix"
    assert body["health"]["status"] == "healthy"
    assert body["summary"]["hosts_total"] == 0
    assert fake_service.calls == 1


def test_zabbix_route_is_mounted_through_shared_router() -> None:
    app = create_app()
    paths = set(app.openapi()["paths"])

    assert "/api/dashboard/zabbix" in paths
