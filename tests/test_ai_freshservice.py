from datetime import datetime, timedelta, timezone

from app.ai.freshservice import AIFreshserviceRepository
from app.db.models import Ticket


NOW = datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc)
START = NOW - timedelta(hours=24)


def ticket(
    ticket_id: int,
    *,
    status_code: int,
    status: str,
    subject: str | None = None,
    priority_code: int = 2,
    priority: str = "medium",
    category: str | None = None,
    due_by=None,
    resolved_at=None,
    closed_at=None,
    is_escalated: bool = False,
) -> Ticket:
    return Ticket(
        source_ticket_id=ticket_id,
        subject=subject or f"Ticket {ticket_id}",
        status_code=status_code,
        status=status,
        priority_code=priority_code,
        priority=priority,
        category=category,
        due_by=due_by,
        is_escalated=is_escalated,
        source_created_at=NOW - timedelta(days=2),
        source_updated_at=NOW - timedelta(minutes=5),
        resolved_at=resolved_at,
        closed_at=closed_at,
        synced_at=NOW - timedelta(minutes=1),
    )


def seed_tickets(auth_env) -> None:
    with auth_env.session_factory() as db:
        db.add_all(
            [
                ticket(
                    1,
                    status_code=2,
                    status="open",
                    subject="VPN access failure",
                    priority_code=4,
                    priority="urgent",
                    category="Network",
                    due_by=NOW - timedelta(hours=2),
                    is_escalated=True,
                ),
                ticket(
                    2,
                    status_code=2,
                    status="open",
                    subject="Printer cannot connect",
                    category="Hardware",
                    due_by=NOW + timedelta(hours=2),
                ),
                ticket(
                    3,
                    status_code=3,
                    status="pending",
                    subject="Awaiting network approval",
                    category="Network",
                ),
                ticket(
                    4,
                    status_code=4,
                    status="resolved",
                    subject="Resolved email issue",
                    category="Software",
                    resolved_at=NOW - timedelta(hours=3),
                ),
                ticket(5, status_code=4, status="resolved", resolved_at=START - timedelta(hours=1)),
                ticket(
                    6,
                    status_code=5,
                    status="closed",
                    resolved_at=NOW - timedelta(hours=5),
                    closed_at=NOW - timedelta(hours=4),
                ),
                ticket(7, status_code=5, status="closed", closed_at=START - timedelta(hours=1)),
            ]
        )
        db.commit()


def test_freshservice_ai_repository_returns_only_requested_ticket_counts(auth_env) -> None:
    seed_tickets(auth_env)

    with auth_env.session_factory() as db:
        repository = AIFreshserviceRepository(db)
        assert repository.metrics_for_question(
            "How many tickets were resolved?",
            start=START,
            end=NOW,
        ) == {"tickets_resolved_in_range": 2}
        assert repository.metrics_for_question(
            "How many tickets were closed, overdue, pending, and currently open?",
            start=START,
            end=NOW,
        ) == {
            "tickets_open_current": 2,
            "tickets_pending_current": 1,
            "tickets_overdue_open_current": 1,
            "tickets_closed_in_range": 1,
        }
        assert repository.metrics_for_question(
            "How many unresolved tickets are there?",
            start=START,
            end=NOW,
        ) == {"tickets_unresolved_current": 3}


def test_freshservice_ai_repository_uses_bounded_default_status_set_for_generic_ticket_question(
    auth_env,
) -> None:
    seed_tickets(auth_env)

    with auth_env.session_factory() as db:
        metrics = AIFreshserviceRepository(db).metrics_for_question(
            "Give me ticket information",
            start=START,
            end=NOW,
        )

    assert metrics == {
        "tickets_open_current": 2,
        "tickets_pending_current": 1,
        "tickets_overdue_open_current": 1,
        "tickets_resolved_in_range": 2,
        "tickets_closed_in_range": 1,
    }


def test_freshservice_ai_repository_returns_bounded_operational_ticket_details(auth_env) -> None:
    seed_tickets(auth_env)

    with auth_env.session_factory() as db:
        repository = AIFreshserviceRepository(db)
        result = repository.ticket_details_for_question(
            "What are the overdue tickets about?",
            start=START,
            end=NOW,
        )

    assert result is not None
    assert result.matching_count == 1
    assert result.truncated is False
    assert len(result.tickets) == 1
    row = result.tickets[0]
    assert row.ticket_id == 1
    assert row.subject == "VPN access failure"
    assert row.status == "open"
    assert row.priority == "urgent"
    assert row.category == "Network"
    assert row.is_overdue is True
    assert row.is_escalated is True
    serialized = result.model_dump_json()
    assert "requester" not in serialized
    assert "responder" not in serialized
    assert "department" not in serialized
    assert "workspace" not in serialized
    assert "group_id" not in serialized


def test_freshservice_ai_ticket_details_support_status_priority_and_topic_filters(auth_env) -> None:
    seed_tickets(auth_env)

    with auth_env.session_factory() as db:
        repository = AIFreshserviceRepository(db)
        network = repository.ticket_details_for_question(
            "Which open tickets are network related?",
            start=START,
            end=NOW,
        )
        urgent_vpn = repository.ticket_details_for_question(
            "Are there any urgent VPN tickets?",
            start=START,
            end=NOW,
        )
        unresolved = repository.ticket_details_for_question(
            "Summarize unresolved tickets",
            start=START,
            end=NOW,
            limit=2,
        )
        attention = repository.ticket_details_for_question(
            "Which tickets need attention first?",
            start=START,
            end=NOW,
        )

    assert network is not None
    assert network.matching_count == 1
    assert [row.ticket_id for row in network.tickets] == [1]
    assert urgent_vpn is not None
    assert urgent_vpn.matching_count == 1
    assert urgent_vpn.tickets[0].subject == "VPN access failure"
    assert unresolved is not None
    assert unresolved.matching_count == 3
    assert len(unresolved.tickets) == 2
    assert unresolved.truncated is True
    assert attention is not None
    assert attention.matching_count == 3
    assert attention.tickets[0].ticket_id == 1


def test_freshservice_ai_ticket_details_are_not_loaded_for_count_only_question(auth_env) -> None:
    seed_tickets(auth_env)

    with auth_env.session_factory() as db:
        result = AIFreshserviceRepository(db).ticket_details_for_question(
            "How many open tickets are there?",
            start=START,
            end=NOW,
        )

    assert result is None
