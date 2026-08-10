from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import IntegrationError
from app.db.models import SyncRun, Ticket
from app.integrations.freshservice.client import FreshserviceClient
from app.integrations.freshservice.models import FreshserviceTicket


FRESHSERVICE_INCREMENTAL_OVERLAP = timedelta(seconds=60)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FreshserviceSyncService:
    """Persist incremental Freshservice ticket snapshots without source-side writes."""

    def __init__(
        self,
        client: FreshserviceClient,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._client = client
        self._clock = clock

    async def sync(self, db: Session) -> SyncRun:
        last_success = db.scalar(
            select(SyncRun)
            .where(SyncRun.source == "freshservice", SyncRun.status == "success")
            .order_by(SyncRun.completed_at.desc(), SyncRun.id.desc())
            .limit(1)
        )
        updated_since = None
        if last_success is not None:
            updated_since = last_success.started_at - FRESHSERVICE_INCREMENTAL_OVERLAP

        run = SyncRun(
            source="freshservice",
            sync_type="incremental" if updated_since is not None else "full",
            status="running",
            started_at=self._clock(),
            records_received=0,
            records_upserted=0,
        )
        db.add(run)
        db.commit()
        run_id = run.id

        try:
            tickets = await self._client.list_tickets(updated_since=updated_since)
        except IntegrationError as exc:
            self._mark_failed(db, run_id, exc.code)
            raise

        completed_at = self._clock()
        unique_tickets = {ticket.ticket_id: ticket for ticket in tickets}
        try:
            existing: dict[int, Ticket] = {}
            if unique_tickets:
                existing = {
                    ticket.source_ticket_id: ticket
                    for ticket in db.scalars(
                        select(Ticket).where(Ticket.source_ticket_id.in_(unique_tickets))
                    )
                }

            for source_ticket_id, ticket in unique_tickets.items():
                record = existing.get(source_ticket_id)
                if record is None:
                    record = Ticket(
                        source_ticket_id=source_ticket_id,
                        subject=ticket.subject,
                        status_code=ticket.status_code,
                        status=ticket.status,
                        priority_code=ticket.priority_code,
                        priority=ticket.priority,
                        source_created_at=ticket.created_at,
                        source_updated_at=ticket.updated_at,
                        synced_at=completed_at,
                    )
                    db.add(record)
                _apply_ticket(record, ticket, synced_at=completed_at)

            persisted_run = db.get(SyncRun, run_id)
            if persisted_run is None:
                raise RuntimeError("Freshservice sync run disappeared")
            persisted_run.status = "success"
            persisted_run.completed_at = completed_at
            persisted_run.records_received = len(tickets)
            persisted_run.records_upserted = len(unique_tickets)
            persisted_run.error_code = None
            db.commit()
            return persisted_run
        except SQLAlchemyError:
            db.rollback()
            self._mark_failed(db, run_id, "SYNC_DATABASE_ERROR")
            raise

    def _mark_failed(self, db: Session, run_id: int, error_code: str) -> None:
        run = db.get(SyncRun, run_id)
        if run is None:
            return
        run.status = "failed"
        run.completed_at = self._clock()
        run.error_code = error_code[:64]
        run.records_upserted = 0
        db.commit()


def _apply_ticket(record: Ticket, ticket: FreshserviceTicket, *, synced_at: datetime) -> None:
    record.subject = ticket.subject
    record.status_code = ticket.status_code
    record.status = ticket.status
    record.priority_code = ticket.priority_code
    record.priority = ticket.priority
    record.ticket_type = ticket.ticket_type
    record.category = ticket.category
    record.sub_category = ticket.sub_category
    record.item_category = ticket.item_category
    record.requester_id = ticket.requester_id
    record.requested_for_id = ticket.requested_for_id
    record.responder_id = ticket.responder_id
    record.group_id = ticket.group_id
    record.department_id = ticket.department_id
    record.workspace_id = ticket.workspace_id
    record.source_code = ticket.source_code
    record.due_by = ticket.due_by
    record.first_response_due_by = ticket.first_response_due_by
    record.is_escalated = ticket.is_escalated
    record.first_response_escalated = ticket.first_response_escalated
    record.source_created_at = ticket.created_at
    record.source_updated_at = ticket.updated_at
    record.resolved_at = ticket.resolved_at
    record.closed_at = ticket.closed_at
    record.first_responded_at = ticket.first_responded_at
    record.synced_at = synced_at
