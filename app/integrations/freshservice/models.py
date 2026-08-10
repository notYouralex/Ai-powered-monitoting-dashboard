from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
