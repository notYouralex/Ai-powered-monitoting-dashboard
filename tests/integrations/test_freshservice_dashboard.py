from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher, Type

from app.db.models import SyncRun, Ticket, User
from app.integrations.freshservice.service import FreshserviceDashboardService


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
                    due_by=NOW - timedelta(days=1),
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
                Ticket(
                    source_ticket_id=104,
                    subject="Waiting for customer",
                    status_code=6,
                    status="unknown",
                    priority_code=2,
                    priority="medium",
                    category="Network",
                    due_by=NOW - timedelta(days=1),
                    source_created_at=NOW - timedelta(days=4),
                    source_updated_at=NOW - timedelta(minutes=7),
                    synced_at=NOW - timedelta(minutes=2),
                ),
                Ticket(
                    source_ticket_id=105,
                    subject="Open ticket due today",
                    status_code=2,
                    status="open",
                    priority_code=2,
                    priority="medium",
                    category="Software",
                    due_by=NOW - timedelta(hours=1),
                    source_created_at=NOW - timedelta(days=1),
                    source_updated_at=NOW - timedelta(minutes=8),
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
                records_received=5,
                records_upserted=5,
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
        "tickets_total": 5,
        "tickets_open": 2,
        "tickets_pending": 2,
        "tickets_resolved": 1,
        "tickets_closed": 0,
        "tickets_unknown": 0,
        "high_priority_open": 1,
        "due_today": 1,
        "overdue_open": 1,
        "escalated_open": 1,
        "resolution_sla_eligible": 0,
        "resolution_sla_met": 0,
        "resolution_sla_compliance_percent": None,
    }
    assert {item["name"]: item["count"] for item in body["status_distribution"]} == {
        "Open": 2,
        "Pending": 1,
        "Pending Customer": 1,
        "Resolved": 1,
    }
    assert {
        item["name"]: item["count"] for item in body["unresolved_status_distribution"]
    } == {
        "Open": 2,
        "Pending": 1,
        "Pending Customer": 1,
    }
    assert {
        item["name"]: item["count"] for item in body["unresolved_priority_distribution"]
    } == {
        "medium": 3,
        "urgent": 1,
    }
    assert body["category_distribution"][0]["count"] >= 1
    assert body["resolution_trend"][0]["count"] == 1
    assert body["recent_tickets"][0]["ticket_id"] == 101


def test_dashboard_historical_metrics_use_six_month_created_date_scope(
    auth_env, monkeypatch
) -> None:
    seed_user_and_tickets(auth_env)
    auth_env.settings.freshservice_base_url = "https://company.freshservice.com"
    auth_env.settings.freshservice_api_key = "fake-key"
    cutoff = datetime(2026, 2, 9, 16, 0, tzinfo=timezone.utc)

    with auth_env.session_factory() as db:
        db.add_all(
            [
                Ticket(
                    source_ticket_id=106,
                    subject="Old ticket still open",
                    status_code=2,
                    status="open",
                    priority_code=2,
                    priority="medium",
                    category="Legacy",
                    source_created_at=cutoff - timedelta(seconds=1),
                    source_updated_at=NOW - timedelta(minutes=9),
                    synced_at=NOW - timedelta(minutes=2),
                ),
                Ticket(
                    source_ticket_id=107,
                    subject="Old ticket closed recently",
                    status_code=5,
                    status="closed",
                    priority_code=2,
                    priority="medium",
                    category="Legacy",
                    source_created_at=cutoff - timedelta(seconds=1),
                    source_updated_at=NOW - timedelta(minutes=10),
                    closed_at=NOW - timedelta(days=1),
                    synced_at=NOW - timedelta(minutes=2),
                ),
                Ticket(
                    source_ticket_id=108,
                    subject="Six month boundary closed ticket",
                    status_code=5,
                    status="closed",
                    priority_code=2,
                    priority="medium",
                    category="Hardware",
                    source_created_at=cutoff,
                    source_updated_at=NOW - timedelta(minutes=11),
                    closed_at=NOW - timedelta(days=1),
                    synced_at=NOW - timedelta(minutes=2),
                ),
            ]
        )
        db.commit()

    login(auth_env)
    monkeypatch.setattr("app.integrations.freshservice.service.utc_now", lambda: NOW)

    response = auth_env.client.get("/api/dashboard/freshservice")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["tickets_open"] == 3
    assert body["summary"]["tickets_closed"] == 1
    assert {item["name"]: item["count"] for item in body["status_distribution"]} == {
        "Open": 2,
        "Pending": 1,
        "Pending Customer": 1,
        "Resolved": 1,
        "Closed": 1,
    }
    assert all(item["name"] != "Legacy" for item in body["category_distribution"])


def test_dashboard_calculates_current_month_resolution_sla_compliance(
    auth_env, monkeypatch
) -> None:
    seed_user_and_tickets(auth_env)
    auth_env.settings.freshservice_base_url = "https://company.freshservice.com"
    auth_env.settings.freshservice_api_key = "fake-key"
    month_start = datetime(2026, 7, 31, 16, 0, tzinfo=timezone.utc)
    next_month_start = datetime(2026, 8, 31, 16, 0, tzinfo=timezone.utc)

    with auth_env.session_factory() as db:
        db.add_all(
            [
                Ticket(
                    source_ticket_id=112,
                    subject="Resolved within SLA from earlier creation month",
                    status_code=4,
                    status="resolved",
                    priority_code=2,
                    priority="medium",
                    due_by=NOW - timedelta(days=2),
                    source_created_at=month_start - timedelta(days=10),
                    source_updated_at=NOW - timedelta(days=3),
                    resolved_at=NOW - timedelta(days=3),
                    synced_at=NOW - timedelta(minutes=2),
                ),
                Ticket(
                    source_ticket_id=113,
                    subject="Closed after SLA",
                    status_code=5,
                    status="closed",
                    priority_code=2,
                    priority="medium",
                    due_by=NOW - timedelta(days=4),
                    source_created_at=NOW - timedelta(days=12),
                    source_updated_at=NOW - timedelta(days=2),
                    resolved_at=NOW - timedelta(days=3),
                    closed_at=NOW - timedelta(days=2),
                    synced_at=NOW - timedelta(minutes=2),
                ),
                Ticket(
                    source_ticket_id=114,
                    subject="Resolved without SLA deadline",
                    status_code=4,
                    status="resolved",
                    priority_code=2,
                    priority="medium",
                    source_created_at=NOW - timedelta(days=8),
                    source_updated_at=NOW - timedelta(days=1),
                    resolved_at=NOW - timedelta(days=1),
                    synced_at=NOW - timedelta(minutes=2),
                ),
                Ticket(
                    source_ticket_id=115,
                    subject="Created this month but resolved before current month",
                    status_code=4,
                    status="resolved",
                    priority_code=2,
                    priority="medium",
                    due_by=month_start - timedelta(hours=1),
                    source_created_at=month_start + timedelta(days=1),
                    source_updated_at=NOW - timedelta(days=4),
                    resolved_at=month_start - timedelta(seconds=1),
                    synced_at=NOW - timedelta(minutes=2),
                ),
                Ticket(
                    source_ticket_id=116,
                    subject="Resolved exactly at current month start",
                    status_code=4,
                    status="resolved",
                    priority_code=2,
                    priority="medium",
                    due_by=month_start + timedelta(hours=1),
                    source_created_at=month_start - timedelta(days=20),
                    source_updated_at=NOW,
                    resolved_at=month_start,
                    synced_at=NOW - timedelta(minutes=2),
                ),
                Ticket(
                    source_ticket_id=117,
                    subject="Resolved exactly at next month start",
                    status_code=4,
                    status="resolved",
                    priority_code=2,
                    priority="medium",
                    due_by=next_month_start + timedelta(hours=1),
                    source_created_at=NOW,
                    source_updated_at=NOW,
                    resolved_at=next_month_start,
                    synced_at=NOW - timedelta(minutes=2),
                ),
                Ticket(
                    source_ticket_id=118,
                    subject="Closed without resolved timestamp",
                    status_code=5,
                    status="closed",
                    priority_code=2,
                    priority="medium",
                    due_by=NOW + timedelta(days=1),
                    source_created_at=NOW,
                    source_updated_at=NOW,
                    synced_at=NOW - timedelta(minutes=2),
                ),
            ]
        )
        db.commit()

    login(auth_env)
    monkeypatch.setattr("app.integrations.freshservice.service.utc_now", lambda: NOW)

    response = auth_env.client.get("/api/dashboard/freshservice")

    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["resolution_sla_eligible"] == 3
    assert summary["resolution_sla_met"] == 2
    assert summary["resolution_sla_compliance_percent"] == 66.7

    with auth_env.session_factory() as db:
        executive = FreshserviceDashboardService(db, auth_env.settings).get_executive_summary()
    assert executive.metrics["resolution_sla_compliance_percent"] == 66.7


def test_dashboard_resolution_sla_trend_is_limited_to_six_calendar_months(
    auth_env, monkeypatch
) -> None:
    seed_user_and_tickets(auth_env)
    auth_env.settings.freshservice_base_url = "https://company.freshservice.com"
    auth_env.settings.freshservice_api_key = "fake-key"

    monthly_resolutions = [
        (120, datetime(2026, 2, 15, 4, 0, tzinfo=timezone.utc), True),
        (121, datetime(2026, 3, 15, 4, 0, tzinfo=timezone.utc), True),
        (122, datetime(2026, 4, 15, 4, 0, tzinfo=timezone.utc), True),
        (123, datetime(2026, 5, 15, 4, 0, tzinfo=timezone.utc), True),
        (124, datetime(2026, 6, 15, 4, 0, tzinfo=timezone.utc), True),
        (125, datetime(2026, 7, 15, 4, 0, tzinfo=timezone.utc), False),
        (126, datetime(2026, 8, 5, 4, 0, tzinfo=timezone.utc), True),
    ]
    with auth_env.session_factory() as db:
        db.add_all(
            [
                Ticket(
                    source_ticket_id=ticket_id,
                    subject=f"SLA trend {resolved_at:%Y-%m}",
                    status_code=4,
                    status="resolved",
                    priority_code=2,
                    priority="medium",
                    due_by=(
                        resolved_at + timedelta(hours=1)
                        if met_sla
                        else resolved_at - timedelta(hours=1)
                    ),
                    source_created_at=resolved_at - timedelta(days=5),
                    source_updated_at=resolved_at,
                    resolved_at=resolved_at,
                    synced_at=NOW - timedelta(minutes=2),
                )
                for ticket_id, resolved_at, met_sla in monthly_resolutions
            ]
        )
        db.commit()

    login(auth_env)
    monkeypatch.setattr("app.integrations.freshservice.service.utc_now", lambda: NOW)

    response = auth_env.client.get("/api/dashboard/freshservice")

    assert response.status_code == 200
    trend = response.json()["resolution_sla_trend"]
    assert [point["month"] for point in trend] == [
        "2026-03-01",
        "2026-04-01",
        "2026-05-01",
        "2026-06-01",
        "2026-07-01",
        "2026-08-01",
    ]
    assert [point["compliance_percent"] for point in trend] == [
        100.0,
        100.0,
        100.0,
        100.0,
        0.0,
        100.0,
    ]

    september_now = datetime(2026, 9, 15, 4, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.integrations.freshservice.service.utc_now", lambda: september_now)

    september_response = auth_env.client.get("/api/dashboard/freshservice")

    assert september_response.status_code == 200
    september_trend = september_response.json()["resolution_sla_trend"]
    assert [point["month"] for point in september_trend] == [
        "2026-04-01",
        "2026-05-01",
        "2026-06-01",
        "2026-07-01",
        "2026-08-01",
        "2026-09-01",
    ]


def test_dashboard_resolution_sla_is_not_controlled_by_request_time_range(
    auth_env, monkeypatch
) -> None:
    seed_user_and_tickets(auth_env)
    auth_env.settings.freshservice_base_url = "https://company.freshservice.com"
    auth_env.settings.freshservice_api_key = "fake-key"

    with auth_env.session_factory() as db:
        db.add(
            Ticket(
                source_ticket_id=119,
                subject="Current-month SLA met",
                status_code=4,
                status="resolved",
                priority_code=2,
                priority="medium",
                due_by=NOW + timedelta(hours=1),
                source_created_at=NOW - timedelta(days=1),
                source_updated_at=NOW,
                resolved_at=NOW,
                synced_at=NOW - timedelta(minutes=2),
            )
        )
        db.commit()

    login(auth_env)
    monkeypatch.setattr("app.integrations.freshservice.service.utc_now", lambda: NOW)

    response = auth_env.client.get(
        "/api/dashboard/freshservice",
        params={
            "from": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
            "to": datetime(2026, 1, 2, tzinfo=timezone.utc).isoformat(),
        },
    )

    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["resolution_sla_eligible"] == 1
    assert summary["resolution_sla_met"] == 1
    assert summary["resolution_sla_compliance_percent"] == 100.0


def test_pending_summary_includes_all_pending_variants_with_six_month_scope(
    auth_env, monkeypatch
) -> None:
    seed_user_and_tickets(auth_env)
    auth_env.settings.freshservice_base_url = "https://company.freshservice.com"
    auth_env.settings.freshservice_api_key = "fake-key"
    cutoff = datetime(2026, 2, 9, 16, 0, tzinfo=timezone.utc)

    with auth_env.session_factory() as db:
        db.add_all(
            [
                Ticket(
                    source_ticket_id=109,
                    subject="Waiting for external resolver",
                    status_code=7,
                    status="pending",
                    priority_code=2,
                    priority="medium",
                    source_created_at=cutoff,
                    source_updated_at=NOW - timedelta(minutes=12),
                    synced_at=NOW - timedelta(minutes=2),
                ),
                Ticket(
                    source_ticket_id=110,
                    subject="Old pending ticket",
                    status_code=3,
                    status="pending",
                    priority_code=2,
                    priority="medium",
                    source_created_at=cutoff - timedelta(seconds=1),
                    source_updated_at=NOW - timedelta(minutes=13),
                    synced_at=NOW - timedelta(minutes=2),
                ),
                Ticket(
                    source_ticket_id=111,
                    subject="Old pending customer ticket",
                    status_code=6,
                    status="pending",
                    priority_code=2,
                    priority="medium",
                    source_created_at=cutoff - timedelta(seconds=1),
                    source_updated_at=NOW - timedelta(minutes=14),
                    synced_at=NOW - timedelta(minutes=2),
                ),
            ]
        )
        db.commit()

    login(auth_env)
    monkeypatch.setattr("app.integrations.freshservice.service.utc_now", lambda: NOW)

    response = auth_env.client.get("/api/dashboard/freshservice")

    assert response.status_code == 200
    assert response.json()["summary"]["tickets_pending"] == 3


def test_dashboard_response_allows_six_month_resolution_trend(auth_env, monkeypatch) -> None:
    seed_user_and_tickets(auth_env)
    auth_env.settings.freshservice_base_url = "https://company.freshservice.com"
    auth_env.settings.freshservice_api_key = "fake-key"

    with auth_env.session_factory() as db:
        for days_ago in range(32, 132):
            db.add(
                Ticket(
                    source_ticket_id=1000 + days_ago,
                    subject=f"Resolved ticket {days_ago}",
                    status_code=4,
                    status="resolved",
                    priority_code=2,
                    priority="medium",
                    category="Software",
                    source_created_at=NOW - timedelta(days=days_ago + 1),
                    source_updated_at=NOW - timedelta(days=days_ago),
                    resolved_at=NOW - timedelta(days=days_ago),
                    synced_at=NOW - timedelta(minutes=2),
                )
            )
        db.commit()

    login(auth_env)
    monkeypatch.setattr("app.integrations.freshservice.service.utc_now", lambda: NOW)

    response = auth_env.client.get("/api/dashboard/freshservice")

    assert response.status_code == 200
    assert len(response.json()["resolution_trend"]) > 31


def test_dashboard_service_builds_bounded_executive_summary(auth_env, monkeypatch) -> None:
    seed_user_and_tickets(auth_env)
    auth_env.settings.freshservice_base_url = "https://company.freshservice.com"
    auth_env.settings.freshservice_api_key = "fake-key"
    monkeypatch.setattr("app.integrations.freshservice.service.utc_now", lambda: NOW)

    with auth_env.session_factory() as db:
        service = FreshserviceDashboardService(db=db, settings=auth_env.settings)
        response = service.get_executive_summary()

    assert response.source == "freshservice"
    assert response.health.source == "freshservice"
    assert response.health.status == "healthy"
    assert response.is_stale is False
    assert response.warnings == []
    assert response.metrics == {
        "tickets_total": 5,
        "tickets_open": 2,
        "tickets_pending": 2,
        "high_priority_open": 1,
        "due_today": 1,
        "overdue_open": 1,
        "escalated_open": 1,
        "resolution_sla_compliance_percent": None,
    }


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
    assert body["summary"]["tickets_total"] == 5
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
