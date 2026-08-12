import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import IntegrationError
from app.db.base import Base
from app.db.models import SyncRun, Ticket
from app.db.session import create_engine_for_url
from app.integrations.freshservice.models import FreshserviceTicket
from app.integrations.freshservice.sync import FreshserviceSyncService


T0 = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 8, 10, 0, 10, tzinfo=timezone.utc)


def normalized_ticket(ticket_id: int = 101, **overrides) -> FreshserviceTicket:
    values = {
        "ticket_id": ticket_id,
        "subject": "VPN unavailable",
        "status_code": 2,
        "status": "open",
        "priority_code": 3,
        "priority": "high",
        "ticket_type": "Incident",
        "category": "Network",
        "requester_id": 1001,
        "responder_id": 2001,
        "due_by": T1 + timedelta(hours=1),
        "is_escalated": False,
        "created_at": T0,
        "updated_at": T1,
    }
    values.update(overrides)
    return FreshserviceTicket(**values)


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.updated_since_calls = []

    async def list_tickets(self, *, updated_since=None):
        self.updated_since_calls.append(updated_since)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_db() -> Session:
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_sync_inserts_then_incrementally_updates_without_duplicates() -> None:
    async def run() -> None:
        db = make_db()
        client = FakeClient(
            [
                [normalized_ticket()],
                [normalized_ticket(subject="VPN restored", updated_at=T1 + timedelta(minutes=10))],
            ]
        )
        clock_values = iter([T1, T1, T1 + timedelta(minutes=10), T1 + timedelta(minutes=10)])
        service = FreshserviceSyncService(client, clock=lambda: next(clock_values))

        first = await service.sync(db)
        second = await service.sync(db)

        tickets = db.scalars(select(Ticket)).all()
        runs = db.scalars(select(SyncRun).order_by(SyncRun.id)).all()

        assert first.status == "success"
        assert second.status == "success"
        assert len(tickets) == 1
        assert tickets[0].source_ticket_id == 101
        assert tickets[0].subject == "VPN restored"
        assert client.updated_since_calls[0] is None
        assert client.updated_since_calls[1] == T1 - timedelta(seconds=60)
        assert [run.records_upserted for run in runs] == [1, 1]
        db.close()

    asyncio.run(run())


def test_incremental_cursor_uses_previous_sync_start_with_overlap() -> None:
    async def run() -> None:
        db = make_db()
        db.add(
            SyncRun(
                source="freshservice",
                sync_type="full",
                status="success",
                started_at=T0,
                completed_at=T1,
                records_received=1,
                records_upserted=1,
            )
        )
        db.commit()
        client = FakeClient([[]])
        clock_values = iter([T1 + timedelta(minutes=5), T1 + timedelta(minutes=5)])
        service = FreshserviceSyncService(client, clock=lambda: next(clock_values))

        await service.sync(db)

        assert client.updated_since_calls == [T0 - timedelta(seconds=60)]
        db.close()

    asyncio.run(run())


def test_failed_sync_preserves_last_valid_ticket_and_records_safe_error_code() -> None:
    async def run() -> None:
        db = make_db()
        db.add(
            Ticket(
                source_ticket_id=101,
                subject="Existing ticket",
                status_code=2,
                status="open",
                priority_code=2,
                priority="medium",
                source_created_at=T0,
                source_updated_at=T0,
                synced_at=T0,
            )
        )
        db.commit()
        error = IntegrationError(
            source="freshservice",
            code="SOURCE_UNAVAILABLE",
            retryable=True,
        )
        client = FakeClient([error])
        clock_values = iter([T1, T1])
        service = FreshserviceSyncService(client, clock=lambda: next(clock_values))

        try:
            await service.sync(db)
        except IntegrationError as exc:
            assert exc.code == "SOURCE_UNAVAILABLE"
        else:
            raise AssertionError("sync should propagate the source error")

        ticket = db.scalar(select(Ticket).where(Ticket.source_ticket_id == 101))
        run_record = db.scalar(select(SyncRun).order_by(SyncRun.id.desc()))
        assert ticket is not None
        assert ticket.subject == "Existing ticket"
        assert run_record is not None
        assert run_record.status == "failed"
        assert run_record.error_code == "SOURCE_UNAVAILABLE"
        assert run_record.records_upserted == 0
        db.close()

    asyncio.run(run())
