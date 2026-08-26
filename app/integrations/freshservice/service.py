from calendar import monthrange
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.contracts import ExecutiveSourceSummary, IntegrationHealthSummary
from app.core.config import Settings
from app.db.models import SyncRun, Ticket
from app.integrations.freshservice.models import (
    FreshserviceDashboardResponse,
    FreshserviceDashboardSummary,
    FreshserviceNamedCount,
    FreshserviceTicket,
    FreshserviceSlaTrendPoint,
    FreshserviceTrendPoint,
)


OPEN_STATUS_CODES = (2,)
PENDING_STATUS_CODES = (3, 6, 7)
RESOLVED_STATUS_CODES = (4,)
CLOSED_STATUS_CODES = (5,)
ACTIVE_STATUS_CODES = OPEN_STATUS_CODES + PENDING_STATUS_CODES
TERMINAL_STATUS_CODES = RESOLVED_STATUS_CODES + CLOSED_STATUS_CODES
KNOWN_SUMMARY_STATUS_CODES = (
    OPEN_STATUS_CODES + PENDING_STATUS_CODES + RESOLVED_STATUS_CODES + CLOSED_STATUS_CODES
)
HIGH_PRIORITIES = ("high", "urgent")
FRESHSERVICE_DASHBOARD_TIMEZONE = ZoneInfo("Asia/Manila")
FRESHSERVICE_STATUS_LABELS = {
    2: "Open",
    3: "Pending",
    4: "Resolved",
    5: "Closed",
    6: "Pending Customer",
    7: "Pending External Resolver",
    8: "Work In Progress",
    9: "N/A",
}


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
        six_month_start = _dashboard_month_start(now, months=6)
        historical_scope = Ticket.source_created_at >= six_month_start
        current_month_start, next_month_start = _dashboard_month_bounds(now)
        current_month_resolution_scope = (
            Ticket.resolved_at >= current_month_start,
            Ticket.resolved_at < next_month_start,
        )
        unresolved = Ticket.status_code.notin_(TERMINAL_STATUS_CODES)
        status_counts = self._status_distribution(historical_scope)
        priority_counts = self._distribution(Ticket.priority, historical_scope)
        unresolved_status_counts = self._status_distribution(unresolved)
        unresolved_priority_counts = self._distribution(Ticket.priority, unresolved)
        category_counts = self._category_distribution(historical_scope)
        day_start, next_day_start = _dashboard_day_bounds(now)
        latest_run = self._latest_run()
        last_success = self._latest_success()
        health_status, is_stale, warnings = self._health_state(
            now=now,
            ticket_count=total,
            latest_run=latest_run,
            last_success=last_success,
        )

        resolution_sla_trend = self._resolution_sla_trend(now)

        resolved_values = self._db.scalars(
            select(Ticket.resolved_at)
            .where(Ticket.resolved_at.is_not(None), historical_scope)
            .order_by(Ticket.resolved_at)
        ).all()
        resolved_by_date = Counter(value.date() for value in resolved_values if value is not None)

        recent_records = self._db.scalars(
            select(Ticket).order_by(Ticket.source_updated_at.desc()).limit(50)
        ).all()

        resolution_sla_criteria = (
            *current_month_resolution_scope,
            Ticket.status_code.in_(TERMINAL_STATUS_CODES),
            Ticket.due_by.is_not(None),
            Ticket.resolved_at.is_not(None),
        )
        resolution_sla_eligible = self._count(*resolution_sla_criteria)
        resolution_sla_met = self._count(
            *resolution_sla_criteria,
            Ticket.resolved_at <= Ticket.due_by,
        )
        resolution_sla_compliance_percent = (
            round((resolution_sla_met / resolution_sla_eligible) * 100, 1)
            if resolution_sla_eligible
            else None
        )

        summary = FreshserviceDashboardSummary(
            tickets_total=total,
            tickets_open=self._count(Ticket.status_code.in_(OPEN_STATUS_CODES)),
            tickets_pending=self._count(
                Ticket.status_code.in_(PENDING_STATUS_CODES), historical_scope
            ),
            tickets_resolved=self._count(
                Ticket.status_code.in_(RESOLVED_STATUS_CODES), historical_scope
            ),
            tickets_closed=self._count(
                Ticket.status_code.in_(CLOSED_STATUS_CODES), historical_scope
            ),
            tickets_unknown=self._count(Ticket.status_code.notin_(KNOWN_SUMMARY_STATUS_CODES)),
            high_priority_open=self._count(
                Ticket.status_code.in_(ACTIVE_STATUS_CODES),
                Ticket.priority.in_(HIGH_PRIORITIES),
            ),
            due_today=self._count(
                Ticket.status_code.in_(OPEN_STATUS_CODES),
                Ticket.due_by.is_not(None),
                Ticket.due_by >= day_start,
                Ticket.due_by < next_day_start,
            ),
            overdue_open=self._count(
                Ticket.status_code.in_(OPEN_STATUS_CODES),
                Ticket.due_by.is_not(None),
                Ticket.due_by < day_start,
            ),
            escalated_open=self._count(
                Ticket.status_code.in_(ACTIVE_STATUS_CODES),
                or_(Ticket.is_escalated.is_(True), Ticket.first_response_escalated.is_(True)),
            ),
            resolution_sla_eligible=resolution_sla_eligible,
            resolution_sla_met=resolution_sla_met,
            resolution_sla_compliance_percent=resolution_sla_compliance_percent,
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
            unresolved_status_distribution=_named_counts(unresolved_status_counts),
            unresolved_priority_distribution=_named_counts(unresolved_priority_counts),
            category_distribution=category_counts,
            resolution_trend=[
                FreshserviceTrendPoint(date=day, count=count)
                for day, count in sorted(resolved_by_date.items())
            ],
            resolution_sla_trend=resolution_sla_trend,
            recent_tickets=[_ticket_from_record(record) for record in recent_records],
            warnings=warnings,
        )

    def get_executive_summary(self) -> ExecutiveSourceSummary:
        dashboard = self.get_dashboard()
        summary = dashboard.summary

        return ExecutiveSourceSummary(
            source="freshservice",
            observed_at=dashboard.observed_at,
            is_stale=dashboard.is_stale,
            health=dashboard.health,
            metrics={
                "tickets_total": summary.tickets_total,
                "tickets_open": summary.tickets_open,
                "tickets_pending": summary.tickets_pending,
                "high_priority_open": summary.high_priority_open,
                "due_today": summary.due_today,
                "overdue_open": summary.overdue_open,
                "escalated_open": summary.escalated_open,
                "resolution_sla_compliance_percent": summary.resolution_sla_compliance_percent,
            },
            warnings=dashboard.warnings,
        )

    def _resolution_sla_trend(self, now: datetime) -> list[FreshserviceSlaTrendPoint]:
        local_now = now.astimezone(FRESHSERVICE_DASHBOARD_TIMEZONE)
        current_month_index = local_now.year * 12 + local_now.month - 1
        months = []
        for offset in range(5, -1, -1):
            year, zero_based_month = divmod(current_month_index - offset, 12)
            months.append(date(year, zero_based_month + 1, 1))

        first_month = months[0]
        first_month_start = datetime(
            first_month.year,
            first_month.month,
            1,
            tzinfo=FRESHSERVICE_DASHBOARD_TIMEZONE,
        ).astimezone(timezone.utc)
        _, next_month_start = _dashboard_month_bounds(now)
        rows = self._db.scalars(
            select(Ticket)
            .where(
                Ticket.status_code.in_(TERMINAL_STATUS_CODES),
                Ticket.due_by.is_not(None),
                Ticket.resolved_at.is_not(None),
                Ticket.resolved_at >= first_month_start,
                Ticket.resolved_at < next_month_start,
            )
        ).all()
        buckets: dict[date, list[bool]] = {month: [] for month in months}
        for ticket in rows:
            month = ticket.resolved_at.astimezone(FRESHSERVICE_DASHBOARD_TIMEZONE).date().replace(day=1)
            buckets[month].append(ticket.resolved_at <= ticket.due_by)
        return [
            FreshserviceSlaTrendPoint(
                month=month,
                compliance_percent=(
                    round((sum(values) / len(values)) * 100, 1)
                    if values
                    else None
                ),
            )
            for month, values in buckets.items()
        ]

    def _count(self, *criteria) -> int:
        statement = select(func.count()).select_from(Ticket)
        if criteria:
            statement = statement.where(*criteria)
        return int(self._db.scalar(statement) or 0)

    def _distribution(self, column, *criteria) -> dict[str, int]:
        statement = select(column, func.count()).select_from(Ticket)
        if criteria:
            statement = statement.where(*criteria)
        rows = self._db.execute(
            statement.group_by(column).order_by(func.count().desc(), column)
        ).all()
        return {str(name): int(count) for name, count in rows if name}

    def _status_distribution(self, *criteria) -> dict[str, int]:
        statement = select(Ticket.status_code, func.count()).select_from(Ticket)
        if criteria:
            statement = statement.where(*criteria)
        rows = self._db.execute(
            statement.group_by(Ticket.status_code).order_by(func.count().desc(), Ticket.status_code)
        ).all()
        return {
            FRESHSERVICE_STATUS_LABELS.get(int(code), f"Status {code}"): int(count)
            for code, count in rows
        }

    def _category_distribution(self, *criteria) -> list[FreshserviceNamedCount]:
        category = func.coalesce(Ticket.category, "Uncategorized")
        statement = select(category, func.count()).select_from(Ticket)
        if criteria:
            statement = statement.where(*criteria)
        rows = self._db.execute(
            statement.group_by(category).order_by(func.count().desc(), category).limit(10)
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


def _dashboard_month_start(now: datetime, *, months: int) -> datetime:
    local_now = now.astimezone(FRESHSERVICE_DASHBOARD_TIMEZONE)
    month_index = local_now.year * 12 + local_now.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(local_now.day, monthrange(year, month)[1])
    start_local = local_now.replace(
        year=year,
        month=month,
        day=day,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    return start_local.astimezone(timezone.utc)


def _dashboard_month_bounds(now: datetime) -> tuple[datetime, datetime]:
    local_now = now.astimezone(FRESHSERVICE_DASHBOARD_TIMEZONE)
    month_start_local = local_now.replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    if month_start_local.month == 12:
        next_month_start_local = month_start_local.replace(
            year=month_start_local.year + 1,
            month=1,
        )
    else:
        next_month_start_local = month_start_local.replace(
            month=month_start_local.month + 1
        )
    return (
        month_start_local.astimezone(timezone.utc),
        next_month_start_local.astimezone(timezone.utc),
    )


def _dashboard_day_bounds(now: datetime) -> tuple[datetime, datetime]:
    local_now = now.astimezone(FRESHSERVICE_DASHBOARD_TIMEZONE)
    day_start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    next_day_start_local = day_start_local + timedelta(days=1)
    return (
        day_start_local.astimezone(timezone.utc),
        next_day_start_local.astimezone(timezone.utc),
    )


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
