from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts import IntegrationHealthSummary


class SnipeItNamedCount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=256)
    count: int = Field(ge=0)


class SnipeItDashboardSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assets_total: int = Field(ge=0)
    assets_assigned: int = Field(ge=0)
    assets_unassigned: int = Field(ge=0)
    assets_missing_serial: int = Field(ge=0)
    assets_missing_asset_tag: int = Field(ge=0)
    warranty_expired: int = Field(ge=0)
    warranty_expiring_soon: int = Field(ge=0)


class SnipeItDashboardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["snipe_it"] = "snipe_it"
    observed_at: datetime
    is_stale: bool = False
    health: IntegrationHealthSummary
    summary: SnipeItDashboardSummary
    status_distribution: list[SnipeItNamedCount] = Field(default_factory=list, max_length=20)
    category_distribution: list[SnipeItNamedCount] = Field(default_factory=list, max_length=10)
    location_distribution: list[SnipeItNamedCount] = Field(default_factory=list, max_length=10)
    warnings: list[str] = Field(default_factory=list, max_length=20)
