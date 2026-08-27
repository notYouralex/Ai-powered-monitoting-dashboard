import re
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.ai.models import AIFreshserviceTicketEvidence, AIFreshserviceTicketSetEvidence
from app.db.models import Ticket
from app.integrations.freshservice.service import (
    ACTIVE_STATUS_CODES,
    OPEN_STATUS_CODES,
    PENDING_STATUS_CODES,
)


_STATUS_TERMS: dict[str, tuple[str, ...]] = {
    "open": ("open", "currently open", "current open"),
    "pending": ("pending",),
    "overdue": ("overdue",),
    "resolved": ("resolved", "resolve"),
    "closed": ("closed", "close"),
    "unresolved": ("unresolved", "active tickets", "active ticket"),
}
_COUNT_TERMS = ("how many", "count", "number of")
_TICKET_TERMS = ("ticket", "tickets", "incident", "incidents")
_SEARCH_STOP_WORDS = {
    "a",
    "about",
    "active",
    "attention",
    "an",
    "any",
    "are",
    "closed",
    "close",
    "currently",
    "current",
    "details",
    "detail",
    "first",
    "give",
    "high",
    "information",
    "incident",
    "incidents",
    "is",
    "list",
    "me",
    "need",
    "of",
    "open",
    "overdue",
    "pending",
    "priority",
    "related",
    "resolved",
    "resolve",
    "show",
    "summarize",
    "summary",
    "tell",
    "the",
    "there",
    "ticket",
    "tickets",
    "urgent",
    "unresolved",
    "what",
    "which",
}
_WORD_RE = re.compile(r"[a-z0-9]+")


class AIFreshserviceRepository:
    """Read-only bounded Freshservice evidence from normalized synchronized ticket records."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def metrics_for_question(
        self,
        question: str,
        *,
        start: datetime,
        end: datetime,
    ) -> dict[str, int]:
        requested = _requested_statuses(question)
        if not requested and _contains_any_term(question, _TICKET_TERMS):
            requested = {"open", "pending", "overdue", "resolved", "closed"}
        if not requested:
            return {}

        metrics: dict[str, int] = {}
        if "open" in requested:
            metrics["tickets_open_current"] = self._count(
                Ticket.status_code.in_(OPEN_STATUS_CODES)
            )
        if "pending" in requested:
            metrics["tickets_pending_current"] = self._count(
                Ticket.status_code.in_(PENDING_STATUS_CODES)
            )
        if "overdue" in requested:
            metrics["tickets_overdue_open_current"] = self._count(
                Ticket.status_code.in_(OPEN_STATUS_CODES),
                Ticket.due_by.is_not(None),
                Ticket.due_by < end,
            )
        if "resolved" in requested:
            metrics["tickets_resolved_in_range"] = self._count(
                Ticket.resolved_at.is_not(None),
                Ticket.resolved_at >= start,
                Ticket.resolved_at <= end,
            )
        if "closed" in requested:
            metrics["tickets_closed_in_range"] = self._count(
                Ticket.closed_at.is_not(None),
                Ticket.closed_at >= start,
                Ticket.closed_at <= end,
            )
        if "unresolved" in requested:
            metrics["tickets_unresolved_current"] = self._count(
                Ticket.status_code.in_(ACTIVE_STATUS_CODES)
            )
        return metrics

    def ticket_details_for_question(
        self,
        question: str,
        *,
        start: datetime,
        end: datetime,
        limit: int = 20,
    ) -> AIFreshserviceTicketSetEvidence | None:
        if limit < 1 or limit > 20:
            raise ValueError("Freshservice AI ticket detail limit must be between 1 and 20")
        if not _is_ticket_detail_question(question):
            return None

        criteria = [_ticket_scope_criterion(question, start=start, end=end)]
        priority_criterion = _priority_criterion(question)
        if priority_criterion is not None:
            criteria.append(priority_criterion)

        search_terms = _search_terms(question)
        if search_terms:
            searchable_columns = (
                Ticket.subject,
                Ticket.ticket_type,
                Ticket.category,
                Ticket.sub_category,
                Ticket.item_category,
            )
            criteria.append(
                or_(
                    *[
                        column.ilike(f"%{term}%")
                        for term in search_terms
                        for column in searchable_columns
                    ]
                )
            )

        matching_count = self._count(*criteria)
        rows = self._db.scalars(
            select(Ticket)
            .where(*criteria)
            .order_by(
                Ticket.is_escalated.desc(),
                Ticket.priority_code.desc(),
                Ticket.source_updated_at.desc(),
            )
            .limit(limit)
        ).all()

        tickets = [
            _ticket_evidence(row, end=end)
            for row in rows
        ]
        return AIFreshserviceTicketSetEvidence(
            matching_count=matching_count,
            tickets=tickets,
            truncated=matching_count > len(tickets),
        )

    def _count(self, *criteria) -> int:
        statement = select(func.count()).select_from(Ticket)
        if criteria:
            statement = statement.where(*criteria)
        return int(self._db.scalar(statement) or 0)


def _requested_statuses(question: str) -> set[str]:
    return {
        status
        for status, terms in _STATUS_TERMS.items()
        if any(_contains_term(question, term) for term in terms)
    }


def _is_ticket_detail_question(question: str) -> bool:
    if not _contains_any_term(question, _TICKET_TERMS):
        return False
    if any(_contains_term(question, term) for term in _COUNT_TERMS):
        return False
    if _contains_term(question, "sla"):
        return False
    return True


def _ticket_scope_criterion(question: str, *, start: datetime, end: datetime):
    requested = _requested_statuses(question)
    if not requested:
        requested = {"unresolved"}

    alternatives = []
    if "open" in requested:
        alternatives.append(Ticket.status_code.in_(OPEN_STATUS_CODES))
    if "pending" in requested:
        alternatives.append(Ticket.status_code.in_(PENDING_STATUS_CODES))
    if "unresolved" in requested:
        alternatives.append(Ticket.status_code.in_(ACTIVE_STATUS_CODES))
    if "overdue" in requested:
        alternatives.append(
            and_(
                Ticket.status_code.in_(OPEN_STATUS_CODES),
                Ticket.due_by.is_not(None),
                Ticket.due_by < end,
            )
        )
    if "resolved" in requested:
        alternatives.append(
            and_(
                Ticket.resolved_at.is_not(None),
                Ticket.resolved_at >= start,
                Ticket.resolved_at <= end,
            )
        )
    if "closed" in requested:
        alternatives.append(
            and_(
                Ticket.closed_at.is_not(None),
                Ticket.closed_at >= start,
                Ticket.closed_at <= end,
            )
        )
    return or_(*alternatives)


def _priority_criterion(question: str):
    if _contains_term(question, "urgent"):
        return Ticket.priority == "urgent"
    if _contains_term(question, "high priority") or _contains_term(question, "high-priority"):
        return Ticket.priority.in_(("high", "urgent"))
    return None


def _search_terms(question: str) -> list[str]:
    terms: list[str] = []
    for token in _WORD_RE.findall(question.casefold()):
        if len(token) < 3 or token in _SEARCH_STOP_WORDS or token.isdigit():
            continue
        if token not in terms:
            terms.append(token)
        if len(terms) >= 3:
            break
    return terms


def _ticket_evidence(ticket: Ticket, *, end: datetime) -> AIFreshserviceTicketEvidence:
    is_overdue = (
        ticket.status_code in OPEN_STATUS_CODES
        and ticket.due_by is not None
        and ticket.due_by < end
    )
    return AIFreshserviceTicketEvidence(
        ticket_id=ticket.source_ticket_id,
        subject=_bounded_text(ticket.subject, 220),
        status=ticket.status,
        priority=ticket.priority,
        ticket_type=_bounded_text(ticket.ticket_type, 128),
        category=_bounded_text(ticket.category, 128),
        sub_category=_bounded_text(ticket.sub_category, 128),
        due_by=ticket.due_by,
        resolved_at=ticket.resolved_at,
        closed_at=ticket.closed_at,
        is_overdue=is_overdue,
        is_escalated=bool(ticket.is_escalated or ticket.first_response_escalated),
    )


def _bounded_text(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped[:limit]


def _contains_any_term(question: str, terms: tuple[str, ...]) -> bool:
    return any(_contains_term(question, term) for term in terms)


def _contains_term(question: str, term: str) -> bool:
    normalized_question = " ".join(_WORD_RE.findall(question.casefold()))
    normalized_term = " ".join(_WORD_RE.findall(term.casefold()))
    return f" {normalized_term} " in f" {normalized_question} "
