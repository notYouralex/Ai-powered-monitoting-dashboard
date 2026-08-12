from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher, Type

from app.db.models import User
from app.integrations.wazuh.models import (
    WazuhDashboardResponse,
    WazuhDashboardSummary,
)
from app.integrations.wazuh.router import get_wazuh_dashboard_service


NOW = datetime(2026, 8, 10, 6, 0, tzinfo=timezone.utc)


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
        self.calls: list[tuple[datetime, datetime]] = []

    async def get_dashboard(self, start: datetime, end: datetime) -> WazuhDashboardResponse:
        self.calls.append((start, end))
        from app.contracts import IntegrationHealthSummary

        return WazuhDashboardResponse(
            observed_at=NOW,
            range_start=start,
            range_end=end,
            health=IntegrationHealthSummary(
                source="wazuh",
                status="healthy",
                observed_at=NOW,
                last_success_at=NOW,
                response_time_ms=1,
            ),
            summary=WazuhDashboardSummary(
                agents_total=0,
                agents_active=0,
                agents_disconnected=0,
                agents_pending=0,
                agents_never_connected=0,
                agents_unknown=0,
                alerts_total=0,
                alerts_low=0,
                alerts_medium=0,
                alerts_high=0,
                alerts_critical=0,
            ),
        )


def test_wazuh_dashboard_requires_authentication(auth_env) -> None:
    response = auth_env.client.get("/api/dashboard/wazuh")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_authenticated_unconfigured_dashboard_returns_safe_source_error(auth_env) -> None:
    create_user(auth_env)
    login(auth_env)

    response = auth_env.client.get("/api/dashboard/wazuh")

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "SOURCE_NOT_CONFIGURED"
    assert body["error"]["source"] == "wazuh"
    assert body["error"]["retryable"] is False
    assert body["error"]["request_id"]
    assert response.headers["X-Request-ID"] == body["error"]["request_id"]


def test_authenticated_dashboard_returns_normalized_response(auth_env) -> None:
    create_user(auth_env)
    login(auth_env)
    fake_service = FakeDashboardService()
    auth_env.client.app.dependency_overrides[get_wazuh_dashboard_service] = lambda: fake_service

    start = "2026-08-10T00:00:00Z"
    end = "2026-08-10T01:00:00Z"
    response = auth_env.client.get(
        "/api/dashboard/wazuh",
        params={"from": start, "to": end},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "wazuh"
    assert body["health"]["status"] == "healthy"
    assert body["summary"]["alerts_total"] == 0
    assert fake_service.calls == [
        (
            datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 10, 1, 0, tzinfo=timezone.utc),
        )
    ]


def test_dashboard_rejects_invalid_or_unbounded_time_ranges(auth_env) -> None:
    create_user(auth_env)
    login(auth_env)
    fake_service = FakeDashboardService()
    auth_env.client.app.dependency_overrides[get_wazuh_dashboard_service] = lambda: fake_service

    reversed_range = auth_env.client.get(
        "/api/dashboard/wazuh",
        params={
            "from": "2026-08-10T02:00:00Z",
            "to": "2026-08-10T01:00:00Z",
        },
    )
    assert reversed_range.status_code == 422

    too_large = auth_env.client.get(
        "/api/dashboard/wazuh",
        params={
            "from": "2026-07-01T00:00:00Z",
            "to": "2026-08-10T00:00:00Z",
        },
    )
    assert too_large.status_code == 422

    naive_time = auth_env.client.get(
        "/api/dashboard/wazuh",
        params={
            "from": "2026-08-10T00:00:00",
            "to": "2026-08-10T01:00:00",
        },
    )
    assert naive_time.status_code == 422

    assert fake_service.calls == []


def test_dashboard_defaults_to_last_24_hours(auth_env, monkeypatch) -> None:
    create_user(auth_env)
    login(auth_env)
    fake_service = FakeDashboardService()
    auth_env.client.app.dependency_overrides[get_wazuh_dashboard_service] = lambda: fake_service

    class FrozenDateTime:
        @classmethod
        def now(cls, tz):
            return NOW

    monkeypatch.setattr("app.integrations.wazuh.router.datetime", FrozenDateTime)
    response = auth_env.client.get("/api/dashboard/wazuh")

    assert response.status_code == 200
    assert fake_service.calls == [(NOW - timedelta(hours=24), NOW)]
