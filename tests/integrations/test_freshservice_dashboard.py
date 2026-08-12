from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher, Type

from app.db.models import SyncRun, Ticket, User


NOW = datetime(2026, 8, 10, 8, 0, tzinfo=timezone.utc)


def seed_user_and_tickets(auth_env) -> None:
    with auth_env.session_factory() as db:
        db.add(
            User(
                username="alice",
                password_hash=PasswordHasher(type=Type.ID).hash("correct horse"),
                is_active=True,
                is_admin=False,
            )
        )
        db.add_all(
            [
                Ticket(
                    source_ticket_id=101,
                    subject="Critical VPN issue",
                    status_code=2,
                    status="open",
                    priority_code=4,
                    priority="urgent",
                    category="Network",
                    due_by=NOW - timedelta(hours=1),
                    is_escalated=True,
                    source_created_at=NOW - timedelta(days=2),
                    source_updated_at=NOW - timedelta(minutes=5),
                    synced_at=NOW - timedelta(minutes=2),
                ),
                Ticket(
                    source_ticket_id=102,
                    subject="Laptop software request",
                    status_code=3,
                    status="pending",
                    priority_code=2,
                    priority="medium",
                    category="Software",
                    source_created_at=NOW - timedelta(days=1),
                    source_updated_at=NOW - timedelta(minutes=6),
                    synced_at=NOW - timedelta(minutes=2),
                ),
                Ticket(
                    source_ticket_id=103,
                    subject="Resolved printer issue",
                    status_code=4,
                    status="resolved",
                    priority_code=1,
                    priority="low",
                    category="Hardware",
                    source_created_at=NOW - timedelta(days=3),
                    source_updated_at=NOW - timedelta(hours=1),
                    resolved_at=NOW - timedelta(hours=1),
                    synced_at=NOW - timedelta(minutes=2),
                ),
            ]
        )
        db.add(
            SyncRun(
                source="freshservice",
                sync_type="full",
                status="success",
                started_at=NOW - timedelta(minutes=3),
                completed_at=NOW - timedelta(minutes=2),
                records_received=3,
                records_upserted=3,
            )
        )
        db.commit()


def login(auth_env) -> None:
    response = auth_env.client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "correct horse"},
    )
    assert response.status_code == 200


def test_freshservice_dashboard_requires_authentication(auth_env) -> None:
    response = auth_env.client.get("/api/dashboard/freshservice")
    assert response.status_code == 401


def test_dashboard_reads_synchronized_reporting_data(auth_env, monkeypatch) -> None:
    seed_user_and_tickets(auth_env)
    auth_env.settings.freshservice_base_url = "https://company.freshservice.com"
    auth_env.settings.freshservice_api_key = "fake-key"
    login(auth_env)
    monkeypatch.setattr("app.integrations.freshservice.service.utc_now", lambda: NOW)

    response = auth_env.client.get("/api/dashboard/freshservice")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "freshservice"
    assert body["health"]["status"] == "healthy"
    assert body["health"]["is_stale"] is False
    assert body["summary"] == {
        "tickets_total": 3,
        "tickets_open": 1,
        "tickets_pending": 1,
        "tickets_resolved": 1,
        "tickets_closed": 0,
        "tickets_unknown": 0,
        "high_priority_open": 1,
        "overdue_open": 1,
        "escalated_open": 1,
    }
    assert body["status_distribution"][0]["count"] >= 1
    assert body["category_distribution"][0]["count"] >= 1
    assert body["resolution_trend"][0]["count"] == 1
    assert body["recent_tickets"][0]["ticket_id"] == 101


def test_dashboard_returns_stale_data_when_latest_sync_failed(auth_env, monkeypatch) -> None:
    seed_user_and_tickets(auth_env)
    auth_env.settings.freshservice_base_url = "https://company.freshservice.com"
    auth_env.settings.freshservice_api_key = "fake-key"
    with auth_env.session_factory() as db:
        db.add(
            SyncRun(
                source="freshservice",
                sync_type="incremental",
                status="failed",
                started_at=NOW - timedelta(minutes=1),
                completed_at=NOW - timedelta(seconds=30),
                error_code="SOURCE_UNAVAILABLE",
            )
        )
        db.commit()
    login(auth_env)
    monkeypatch.setattr("app.integrations.freshservice.service.utc_now", lambda: NOW)

    response = auth_env.client.get("/api/dashboard/freshservice")

    assert response.status_code == 200
    body = response.json()
    assert body["health"]["status"] == "degraded"
    assert body["health"]["is_stale"] is True
    assert body["summary"]["tickets_total"] == 3
    assert body["warnings"]


def test_unconfigured_dashboard_reports_not_configured_without_source_call(auth_env) -> None:
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
    login(auth_env)

    response = auth_env.client.get("/api/dashboard/freshservice")

    assert response.status_code == 200
    body = response.json()
    assert body["health"]["status"] == "not_configured"
    assert body["summary"]["tickets_total"] == 0
