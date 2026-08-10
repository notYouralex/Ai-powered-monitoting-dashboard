from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts import IntegrationHealthSummary


FreshserviceTicketStatus = Literal["open", "pending", "resolved", "closed", "unknown"]
FreshserviceTicketPriority = Literal["low", "medium", "high", "urgent", "unknown"]


class FreshserviceTicket(BaseModel):
    """Normalized read-only ticket fields used by reporting and synchronization."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: int = Field(gt=0)
    subject: str = Field(min_length=1, max_length=1024)
    status_code: int = Field(gt=0)
    status: FreshserviceTicketStatus
    priority_code: int = Field(gt=0)
    priority: FreshserviceTicketPriority
    ticket_type: str | None = Field(default=None, max_length=256)
    category: str | None = Field(default=None, max_length=256)
    sub_category: str | None = Field(default=None, max_length=256)
    item_category: str | None = Field(default=None, max_length=256)
    requester_id: int | None = Field(default=None, gt=0)
    requested_for_id: int | None = Field(default=None, gt=0)
    responder_id: int | None = Field(default=None, gt=0)
    group_id: int | None = Field(default=None, gt=0)
    department_id: int | None = Field(default=None, gt=0)
    workspace_id: int | None = Field(default=None, gt=0)
    source_code: int | None = Field(default=None, gt=0)
    due_by: datetime | None = None
    first_response_due_by: datetime | None = None
    is_escalated: bool = False
    first_response_escalated: bool = False
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    first_responded_at: datetime | None = None


class FreshserviceNamedCount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=256)
    count: int = Field(ge=0)


class FreshserviceTrendPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    count: int = Field(ge=0)


class FreshserviceDashboardSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tickets_total: int = Field(ge=0)
    tickets_open: int = Field(ge=0)
    tickets_pending: int = Field(ge=0)
    tickets_resolved: int = Field(ge=0)
    tickets_closed: int = Field(ge=0)
    tickets_unknown: int = Field(ge=0)
    high_priority_open: int = Field(ge=0)
    overdue_open: int = Field(ge=0)
    escalated_open: int = Field(ge=0)


class FreshserviceDashboardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["freshservice"] = "freshservice"
    observed_at: datetime
    is_stale: bool = False
    health: IntegrationHealthSummary
    summary: FreshserviceDashboardSummary
    status_distribution: list[FreshserviceNamedCount] = Field(default_factory=list, max_length=16)
    priority_distribution: list[FreshserviceNamedCount] = Field(default_factory=list, max_length=16)
    category_distribution: list[FreshserviceNamedCount] = Field(default_factory=list, max_length=10)
    resolution_trend: list[FreshserviceTrendPoint] = Field(default_factory=list, max_length=31)
    recent_tickets: list[FreshserviceTicket] = Field(default_factory=list, max_length=50)
    warnings: list[str] = Field(default_factory=list, max_length=20)
