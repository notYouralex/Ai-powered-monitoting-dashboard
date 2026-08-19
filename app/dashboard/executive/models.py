from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts import ExecutiveSourceSummary, IntegrationSource


EXECUTIVE_SOURCES: tuple[IntegrationSource, ...] = (
    "wazuh",
    "zabbix",
    "snipe_it",
    "freshservice",
)


class ExecutiveDashboardSummary(BaseModel):
    """Render-ready headline metrics derived from normalized source summaries."""

    model_config = ConfigDict(extra="forbid")

    overall_health_percent: int = Field(default=0, ge=0, le=100)
    active_alerts: int = Field(default=0, ge=0)
    tickets_open: int = Field(default=0, ge=0)
    overdue_open: int = Field(default=0, ge=0)
    assets_total: int = Field(default=0, ge=0)


class ExecutiveNamedCount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    count: int = Field(ge=0)


class ExecutiveAttentionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=32)
    issue: str = Field(min_length=1, max_length=128)
    count: int = Field(ge=0)


class ExecutiveDashboardResponse(BaseModel):
    """Bounded cross-source Executive response built only from normalized summaries."""

    model_config = ConfigDict(extra="forbid")

    observed_at: datetime
    range_start: datetime
    range_end: datetime
    summary: ExecutiveDashboardSummary = Field(default_factory=ExecutiveDashboardSummary)
    health_distribution: list[ExecutiveNamedCount] = Field(default_factory=list, max_length=4)
    alert_category_distribution: list[ExecutiveNamedCount] = Field(
        default_factory=list,
        max_length=2,
    )
    ticket_status_distribution: list[ExecutiveNamedCount] = Field(
        default_factory=list,
        max_length=2,
    )
    attention_required: list[ExecutiveAttentionItem] = Field(default_factory=list, max_length=10)
    sources: list[ExecutiveSourceSummary] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def validate_sources(self) -> "ExecutiveDashboardResponse":
        source_names = [summary.source for summary in self.sources]
        if source_names != list(EXECUTIVE_SOURCES):
            raise ValueError("Executive sources must contain each canonical source in order")
        return self
