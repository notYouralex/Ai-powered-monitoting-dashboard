from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.contracts import IntegrationHealthSummary
from app.core.config import Settings
from app.db.models import SyncRun, Ticket
from app.integrations.freshservice.models import (
    FreshserviceDashboardResponse,
    FreshserviceDashboardSummary,
    FreshserviceNamedCount,
    FreshserviceTicket,
    FreshserviceTrendPoint,
)


OPEN_TICKET_STATES = ("open", "pending")
HIGH_PRIORITIES = ("high", "urgent")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FreshserviceDashboardService:
    """Build Grafana-facing Freshservice data exclusively from synchronized PostgreSQL records."""

    def __init__(self, db: Session, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    def get_dashboard(self) -> FreshserviceDashboardResponse:
        now = utc_now()
        total = self._count()
        status_counts = self._distribution(Ticket.status)
        priority_counts = self._distribution(Ticket.priority)
        category_counts = self._category_distribution()
        latest_run = self._latest_run()
        last_success = self._latest_success()
        health_status, is_stale, warnings = self._health_state(
            now=now,
            ticket_count=total,
            latest_run=latest_run,
            last_success=last_success,
        )

        resolved_since = now - timedelta(days=30)
        resolved_values = self._db.scalars(
            select(Ticket.resolved_at)
            .where(Ticket.resolved_at.is_not(None), Ticket.resolved_at >= resolved_since)
            .order_by(Ticket.resolved_at)
        ).all()
        resolved_by_date = Counter(value.date() for value in resolved_values if value is not None)

        recent_records = self._db.scalars(
            select(Ticket).order_by(Ticket.source_updated_at.desc()).limit(50)
        ).all()

        summary = FreshserviceDashboardSummary(
            tickets_total=total,
            tickets_open=status_counts.get("open", 0),
            tickets_pending=status_counts.get("pending", 0),
            tickets_resolved=status_counts.get("resolved", 0),
            tickets_closed=status_counts.get("closed", 0),
            tickets_unknown=status_counts.get("unknown", 0),
            high_priority_open=self._count(
                Ticket.status.in_(OPEN_TICKET_STATES),
                Ticket.priority.in_(HIGH_PRIORITIES),
            ),
            overdue_open=self._count(
                Ticket.status.in_(OPEN_TICKET_STATES),
                Ticket.due_by.is_not(None),
                Ticket.due_by < now,
            ),
            escalated_open=self._count(
                Ticket.status.in_(OPEN_TICKET_STATES),
                or_(Ticket.is_escalated.is_(True), Ticket.first_response_escalated.is_(True)),
            ),
        )

        health = IntegrationHealthSummary(
            source="freshservice",
            status=health_status,
            observed_at=now,
            last_success_at=last_success.completed_at if last_success is not None else None,
            is_stale=is_stale,
            warnings=warnings,
        )
        return FreshserviceDashboardResponse(
            observed_at=now,
            is_stale=is_stale,
            health=health,
            summary=summary,
            status_distribution=_named_counts(status_counts),
            priority_distribution=_named_counts(priority_counts),
            category_distribution=category_counts,
            resolution_trend=[
                FreshserviceTrendPoint(date=day, count=count)
                for day, count in sorted(resolved_by_date.items())
            ],
            recent_tickets=[_ticket_from_record(record) for record in recent_records],
            warnings=warnings,
        )

    def _count(self, *criteria) -> int:
        statement = select(func.count()).select_from(Ticket)
        if criteria:
            statement = statement.where(*criteria)
        return int(self._db.scalar(statement) or 0)

    def _distribution(self, column) -> dict[str, int]:
        rows = self._db.execute(
            select(column, func.count())
            .select_from(Ticket)
            .group_by(column)
            .order_by(func.count().desc(), column)
        ).all()
        return {str(name): int(count) for name, count in rows if name}

    def _category_distribution(self) -> list[FreshserviceNamedCount]:
        category = func.coalesce(Ticket.category, "Uncategorized")
        rows = self._db.execute(
            select(category, func.count())
            .select_from(Ticket)
            .group_by(category)
            .order_by(func.count().desc(), category)
            .limit(10)
        ).all()
        return [FreshserviceNamedCount(name=str(name), count=int(count)) for name, count in rows]

    def _latest_run(self) -> SyncRun | None:
        return self._db.scalar(
            select(SyncRun)
            .where(SyncRun.source == "freshservice")
            .order_by(SyncRun.started_at.desc(), SyncRun.id.desc())
            .limit(1)
        )

    def _latest_success(self) -> SyncRun | None:
        return self._db.scalar(
            select(SyncRun)
            .where(SyncRun.source == "freshservice", SyncRun.status == "success")
            .order_by(SyncRun.completed_at.desc(), SyncRun.id.desc())
            .limit(1)
        )

    def _health_state(
        self,
        *,
        now: datetime,
        ticket_count: int,
        latest_run: SyncRun | None,
        last_success: SyncRun | None,
    ) -> tuple[str, bool, list[str]]:
        warnings: list[str] = []
        configured = self._settings.integration_config_state("freshservice") == "configured"

        if not configured:
            if ticket_count:
                warnings.append("Freshservice is not configured; showing previously synchronized data.")
            return "not_configured", ticket_count > 0, warnings

        if last_success is None:
            if latest_run is not None and latest_run.status == "failed":
                warnings.append("Freshservice has not completed a successful synchronization.")
                return "unavailable", ticket_count > 0, warnings
            warnings.append("Freshservice has not completed its initial synchronization.")
            return "degraded", ticket_count > 0, warnings

        is_stale = False
        status = "healthy"
        if latest_run is not None and latest_run.id != last_success.id and latest_run.status == "failed":
            warnings.append("The latest Freshservice synchronization failed; showing last successful data.")
            status = "degraded"
            is_stale = True

        if last_success.completed_at is not None:
            stale_after = timedelta(seconds=self._settings.freshservice_sync_interval_seconds * 2)
            if now - last_success.completed_at > stale_after:
                warnings.append("Freshservice synchronized data is older than the expected refresh window.")
                status = "degraded"
                is_stale = True

        return status, is_stale, warnings


def _named_counts(counts: dict[str, int]) -> list[FreshserviceNamedCount]:
    return [
        FreshserviceNamedCount(name=name, count=count)
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _ticket_from_record(record: Ticket) -> FreshserviceTicket:
    return FreshserviceTicket(
        ticket_id=record.source_ticket_id,
        subject=record.subject,
        status_code=record.status_code,
        status=record.status,
        priority_code=record.priority_code,
        priority=record.priority,
        ticket_type=record.ticket_type,
        category=record.category,
        sub_category=record.sub_category,
        item_category=record.item_category,
        requester_id=record.requester_id,
        requested_for_id=record.requested_for_id,
        responder_id=record.responder_id,
        group_id=record.group_id,
        department_id=record.department_id,
        workspace_id=record.workspace_id,
        source_code=record.source_code,
        due_by=record.due_by,
        first_response_due_by=record.first_response_due_by,
        is_escalated=record.is_escalated,
        first_response_escalated=record.first_response_escalated,
        created_at=record.source_created_at,
        updated_at=record.source_updated_at,
        resolved_at=record.resolved_at,
        closed_at=record.closed_at,
        first_responded_at=record.first_responded_at,
    )
