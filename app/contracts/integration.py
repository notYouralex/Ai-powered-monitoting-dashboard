from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)


IntegrationSource: TypeAlias = Literal["wazuh", "zabbix", "snipe_it", "freshservice"]
IntegrationStatus: TypeAlias = Literal["healthy", "degraded", "unavailable", "not_configured"]

WarningText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]
MetricKey = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]
ExecutiveMetricValue: TypeAlias = StrictBool | StrictInt | StrictFloat | StrictStr | None


class IntegrationHealthSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: IntegrationSource
    status: IntegrationStatus
    observed_at: datetime
    last_success_at: datetime | None = None
    response_time_ms: int | None = Field(default=None, ge=0)
    is_stale: bool = False
    warnings: list[WarningText] = Field(default_factory=list, max_length=20)


class ExecutiveSourceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: IntegrationSource
    observed_at: datetime
    is_stale: bool = False
    health: IntegrationHealthSummary
    metrics: dict[MetricKey, ExecutiveMetricValue] = Field(default_factory=dict, max_length=32)
    warnings: list[WarningText] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_health_source(self) -> "ExecutiveSourceSummary":
        if self.health.source != self.source:
            raise ValueError("health source must match Executive summary source")
        return self
