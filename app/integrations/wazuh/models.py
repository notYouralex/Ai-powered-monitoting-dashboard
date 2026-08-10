from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts import IntegrationHealthSummary


WazuhAgentStatus = Literal[
    "active",
    "pending",
    "never_connected",
    "disconnected",
    "unknown",
]


class WazuhAlert(BaseModel):
    """Normalized alert data returned from the Wazuh indexer."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    rule_id: str = Field(min_length=1, max_length=64)
    rule_level: int = Field(ge=0, le=16)
    description: str = Field(min_length=1, max_length=2048)
    agent_id: str | None = Field(default=None, max_length=64)
    agent_name: str | None = Field(default=None, max_length=256)
    groups: list[str] = Field(default_factory=list, max_length=64)


class WazuhNamedCount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=256)
    count: int = Field(ge=0)


class WazuhTrendPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    count: int = Field(ge=0)


class WazuhAlertSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_alerts: int = Field(ge=0)
    severity_levels: dict[int, int] = Field(default_factory=dict)
    top_agents: list[WazuhNamedCount] = Field(default_factory=list, max_length=10)
    trend: list[WazuhTrendPoint] = Field(default_factory=list, max_length=512)
    alerts: list[WazuhAlert] = Field(default_factory=list, max_length=50)


class WazuhDashboardSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agents_total: int = Field(ge=0)
    agents_active: int = Field(ge=0)
    agents_disconnected: int = Field(ge=0)
    agents_pending: int = Field(ge=0)
    agents_never_connected: int = Field(ge=0)
    agents_unknown: int = Field(ge=0)
    alerts_total: int = Field(ge=0)
    alerts_low: int = Field(ge=0)
    alerts_medium: int = Field(ge=0)
    alerts_high: int = Field(ge=0)
    alerts_critical: int = Field(ge=0)


class WazuhAgent(BaseModel):
    """Normalized read-only agent data exposed by the Wazuh adapter."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=256)
    ip: str | None = Field(default=None, max_length=256)
    status: WazuhAgentStatus
    manager: str | None = Field(default=None, max_length=256)
    node_name: str | None = Field(default=None, max_length=256)
    groups: list[str] = Field(default_factory=list, max_length=64)
    last_keep_alive: datetime | None = None
    os_name: str | None = Field(default=None, max_length=256)
    os_version: str | None = Field(default=None, max_length=256)
    os_platform: str | None = Field(default=None, max_length=256)
    os_arch: str | None = Field(default=None, max_length=256)


class WazuhDashboardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["wazuh"] = "wazuh"
    observed_at: datetime
    range_start: datetime
    range_end: datetime
    is_stale: bool = False
    health: IntegrationHealthSummary
    summary: WazuhDashboardSummary
    agents: list[WazuhAgent] = Field(default_factory=list, max_length=10000)
    top_agents: list[WazuhNamedCount] = Field(default_factory=list, max_length=10)
    alert_trend: list[WazuhTrendPoint] = Field(default_factory=list, max_length=512)
    recent_alerts: list[WazuhAlert] = Field(default_factory=list, max_length=50)
    warnings: list[str] = Field(default_factory=list, max_length=20)
