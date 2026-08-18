from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts import ExecutiveSourceSummary, IntegrationSource


EXECUTIVE_SOURCES: tuple[IntegrationSource, ...] = (
    "wazuh",
    "zabbix",
    "snipe_it",
    "freshservice",
)


class ExecutiveDashboardResponse(BaseModel):
    """Bounded cross-source Executive response built only from normalized summaries."""

    model_config = ConfigDict(extra="forbid")

    observed_at: datetime
    range_start: datetime
    range_end: datetime
    sources: list[ExecutiveSourceSummary] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def validate_sources(self) -> "ExecutiveDashboardResponse":
        source_names = [summary.source for summary in self.sources]
        if source_names != list(EXECUTIVE_SOURCES):
            raise ValueError("Executive sources must contain each canonical source in order")
        return self
