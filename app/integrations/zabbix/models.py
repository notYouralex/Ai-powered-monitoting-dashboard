from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts import IntegrationHealthSummary


ZabbixInterfaceType = Literal["agent", "snmp", "ipmi", "jmx", "unknown"]
ZabbixAvailability = Literal["available", "unavailable", "unknown"]
ZabbixProblemSeverity = Literal[
    "not_classified",
    "information",
    "warning",
    "average",
    "high",
    "disaster",
    "unknown",
]


class ZabbixHostInterface(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interface_id: str = Field(min_length=1, max_length=64)
    type: ZabbixInterfaceType
    is_main: bool
    address: str | None = Field(default=None, max_length=512)
    availability: ZabbixAvailability


class ZabbixHost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_id: str = Field(min_length=1, max_length=64)
    technical_name: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=256)
    enabled: bool
    in_maintenance: bool
    interfaces: list[ZabbixHostInterface] = Field(default_factory=list, max_length=32)


class ZabbixProblemHost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_id: str = Field(min_length=1, max_length=64)
    technical_name: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=256)


class ZabbixProblem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=64)
    trigger_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=2048)
    severity: ZabbixProblemSeverity
    started_at: datetime
    acknowledged: bool
    suppressed: bool
    hosts: list[ZabbixProblemHost] = Field(default_factory=list, max_length=32)


class ZabbixDashboardSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hosts_total: int = Field(ge=0)
    hosts_enabled: int = Field(ge=0)
    hosts_disabled: int = Field(ge=0)
    hosts_in_maintenance: int = Field(ge=0)
    interfaces_available: int = Field(ge=0)
    interfaces_unavailable: int = Field(ge=0)
    interfaces_unknown: int = Field(ge=0)
    problems_total: int = Field(ge=0)
    problems_not_classified: int = Field(ge=0)
    problems_information: int = Field(ge=0)
    problems_warning: int = Field(ge=0)
    problems_average: int = Field(ge=0)
    problems_high: int = Field(ge=0)
    problems_disaster: int = Field(ge=0)
    problems_unknown: int = Field(ge=0)
    problems_unacknowledged: int = Field(ge=0)
    problems_suppressed: int = Field(ge=0)


class ZabbixDashboardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["zabbix"] = "zabbix"
    observed_at: datetime
    health: IntegrationHealthSummary
    summary: ZabbixDashboardSummary
    hosts: list[ZabbixHost] = Field(default_factory=list, max_length=5000)
    active_problems: list[ZabbixProblem] = Field(default_factory=list, max_length=1000)
    warnings: list[str] = Field(default_factory=list, max_length=20)
