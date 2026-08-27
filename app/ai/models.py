from datetime import date, datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.contracts import IntegrationSource, IntegrationStatus


AIConfidence: TypeAlias = Literal["low", "medium", "high"]
AIPurpose: TypeAlias = Literal["summary", "investigation"]
AIQuestionScope: TypeAlias = Literal["environment", "source", "device"]
AIMetricValue: TypeAlias = StrictBool | StrictInt | StrictFloat
AIAttentionMetric: TypeAlias = Literal[
    "agents_disconnected",
    "alerts_high",
    "alerts_critical",
    "vulnerabilities_high",
    "vulnerabilities_critical",
    "vulnerable_agents",
    "interfaces_unavailable",
    "problems_high",
    "problems_disaster",
    "problems_unacknowledged",
    "assets_unassigned",
    "assets_missing_serial",
    "assets_missing_asset_tag",
    "warranty_expired",
    "warranty_expiring_soon",
    "tickets_open",
    "tickets_pending",
    "high_priority_open",
    "due_today",
    "overdue_open",
    "escalated_open",
]

BoundedText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
]
BoundedListText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]


class AIQueryRequest(BaseModel):
    """Bounded user question contract for the interactive AI query endpoint."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)

    @field_validator("question", mode="before")
    @classmethod
    def strip_question(cls, value):
        if not isinstance(value, str):
            return value
        return value.strip()


class AIAnalysis(BaseModel):
    """Strict structured model output validated before it reaches an API response."""

    model_config = ConfigDict(extra="forbid")

    summary: BoundedText
    likely_explanation: BoundedText | None = None
    contributing_factors: list[BoundedListText] = Field(default_factory=list, max_length=8)
    evidence: list[BoundedListText] = Field(default_factory=list, max_length=12)
    operational_impact: BoundedText | None = None
    recommended_investigation: list[BoundedListText] = Field(default_factory=list, max_length=8)
    confidence: AIConfidence
    warnings: list[BoundedListText] = Field(default_factory=list, max_length=10)


class AIInvestigationModelOutput(BaseModel):
    """Minimal model-controlled interpretation for interactive investigations."""

    model_config = ConfigDict(extra="forbid")

    likely_explanation: BoundedText | None = None
    recommended_investigation: list[BoundedListText] = Field(default_factory=list, max_length=6)
    confidence: AIConfidence


class AISourceEvidence(BaseModel):
    """Small normalized source snapshot permitted to enter an AI prompt."""

    model_config = ConfigDict(extra="forbid")

    source: IntegrationSource
    status: IntegrationStatus
    is_stale: bool = False
    metrics: dict[str, AIMetricValue] = Field(default_factory=dict, max_length=8)
    health_reasons: list[BoundedListText] = Field(default_factory=list, max_length=4)


class AIExecutiveEvidence(BaseModel):
    """Bounded Executive evidence built only from normalized source summaries."""

    model_config = ConfigDict(extra="forbid")

    observed_at: datetime
    range_start: datetime
    range_end: datetime
    sources: list[AISourceEvidence] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def validate_source_order(self) -> "AIExecutiveEvidence":
        expected = ["wazuh", "zabbix", "snipe_it", "freshservice"]
        if [source.source for source in self.sources] != expected:
            raise ValueError("AI Executive evidence must contain canonical sources in order")
        return self


class AIAttentionSignal(BaseModel):
    """Application-derived nonzero adverse counter permitted in summary prompts."""

    model_config = ConfigDict(extra="forbid")

    source: IntegrationSource
    metric: AIAttentionMetric
    value: StrictInt = Field(gt=0)


class AIAffectedSource(BaseModel):
    """Source state included only when health is nonhealthy or data is stale."""

    model_config = ConfigDict(extra="forbid")

    source: IntegrationSource
    status: IntegrationStatus
    is_stale: bool = False


class AIExecutiveSummaryEvidence(BaseModel):
    """Small application-derived evidence used by the fast summary model."""

    model_config = ConfigDict(extra="forbid")

    observed_at: datetime
    range_start: datetime
    range_end: datetime
    attention_signals: list[AIAttentionSignal] = Field(default_factory=list, max_length=24)
    affected_sources: list[AIAffectedSource] = Field(default_factory=list, max_length=4)


class AICorrelatedDeviceEvidence(BaseModel):
    """Minimal correlated device identity permitted to enter an AI investigation."""

    model_config = ConfigDict(extra="forbid")

    device_id: int = Field(gt=0)
    canonical_name: str = Field(min_length=1, max_length=255)
    hostname: str | None = Field(default=None, max_length=255)
    asset_tag: str | None = Field(default=None, max_length=255)
    correlation_confidence: int = Field(ge=0, le=100)
    linked_sources: list[IntegrationSource] = Field(default_factory=list, max_length=4)


class AIFreshserviceTicketEvidence(BaseModel):
    """Bounded operational Freshservice ticket fields permitted in AI evidence."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: int = Field(gt=0)
    subject: BoundedListText | None = None
    status: str = Field(min_length=1, max_length=32)
    priority: str = Field(min_length=1, max_length=32)
    ticket_type: str | None = Field(default=None, max_length=128)
    category: str | None = Field(default=None, max_length=128)
    sub_category: str | None = Field(default=None, max_length=128)
    due_by: datetime | None = None
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    is_overdue: bool = False
    is_escalated: bool = False


class AIFreshserviceTicketSetEvidence(BaseModel):
    """Bounded Freshservice ticket-detail result for one investigation question."""

    model_config = ConfigDict(extra="forbid")

    matching_count: int = Field(ge=0)
    tickets: list[AIFreshserviceTicketEvidence] = Field(default_factory=list, max_length=20)
    truncated: bool = False


class AISnipeItAssetEvidence(BaseModel):
    """Bounded operational Snipe-IT asset fields permitted in AI evidence."""

    model_config = ConfigDict(extra="forbid")

    asset_tag: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, max_length=255)
    model: str | None = Field(default=None, max_length=128)
    manufacturer: str | None = Field(default=None, max_length=128)
    category: str | None = Field(default=None, max_length=128)
    status_label: str | None = Field(default=None, max_length=128)
    location: str | None = Field(default=None, max_length=128)
    purchase_date: date | None = None
    warranty_expires: date | None = None
    is_assigned: bool
    warranty_state: Literal["expired", "expiring_soon", "active", "unknown"]
    missing_asset_tag: bool = False


class AISnipeItAssetSetEvidence(BaseModel):
    """Bounded Snipe-IT asset-detail result for one investigation question."""

    model_config = ConfigDict(extra="forbid")

    matching_count: int = Field(ge=0)
    assets: list[AISnipeItAssetEvidence] = Field(default_factory=list, max_length=20)
    truncated: bool = False


class AIWazuhNamedCountEvidence(BaseModel):
    """Bounded normalized Wazuh named aggregate permitted in AI evidence."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    count: int = Field(ge=0)


class AIWazuhAlertEvidence(BaseModel):
    """Bounded normalized Wazuh alert fields without rule or agent IDs."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    rule_level: int = Field(ge=0, le=16)
    description: BoundedListText
    agent_name: str | None = Field(default=None, max_length=128)
    groups: list[str] = Field(default_factory=list, max_length=5)


class AIWazuhVulnerabilityEvidence(BaseModel):
    """Bounded normalized Wazuh vulnerability fields without agent IDs."""

    model_config = ConfigDict(extra="forbid")

    vulnerability_id: str = Field(min_length=1, max_length=128)
    severity: str = Field(min_length=1, max_length=32)
    score: float | None = Field(default=None, ge=0, le=10)
    detected_at: datetime | None = None
    agent_name: str | None = Field(default=None, max_length=128)
    package_name: str | None = Field(default=None, max_length=128)
    package_version: str | None = Field(default=None, max_length=128)
    description: BoundedListText | None = None


class AIWazuhAgentEvidence(BaseModel):
    """Bounded Wazuh agent state without agent ID or IP address."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    status: Literal["active", "pending", "never_connected", "disconnected", "unknown"]
    last_keep_alive: datetime | None = None
    os_name: str | None = Field(default=None, max_length=128)
    os_version: str | None = Field(default=None, max_length=128)
    os_platform: str | None = Field(default=None, max_length=64)
    os_arch: str | None = Field(default=None, max_length=64)
    groups: list[str] = Field(default_factory=list, max_length=5)


class AIWazuhDetailEvidence(BaseModel):
    """Bounded Wazuh detail selected from normalized dashboard data."""

    model_config = ConfigDict(extra="forbid")

    recent_alert_matches: int = Field(default=0, ge=0, le=50)
    alerts: list[AIWazuhAlertEvidence] = Field(default_factory=list, max_length=10)
    recent_vulnerability_matches: int = Field(default=0, ge=0, le=20)
    vulnerabilities: list[AIWazuhVulnerabilityEvidence] = Field(default_factory=list, max_length=10)
    agent_matches: int = Field(default=0, ge=0, le=10000)
    agents: list[AIWazuhAgentEvidence] = Field(default_factory=list, max_length=10)
    mitre_tactics: list[AIWazuhNamedCountEvidence] = Field(default_factory=list, max_length=10)
    mitre_techniques: list[AIWazuhNamedCountEvidence] = Field(default_factory=list, max_length=10)


class AIZabbixHostProblemEvidence(BaseModel):
    """Bounded normalized Zabbix problem context for one correlated host."""

    model_config = ConfigDict(extra="forbid")

    name: BoundedListText
    severity: str = Field(min_length=1, max_length=32)
    acknowledged: bool
    suppressed: bool


class AIZabbixHostEvidence(BaseModel):
    """Bounded host-specific Zabbix evidence without source IDs or interface addresses."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["available", "unavailable", "unknown", "maintenance", "disabled"]
    unavailable_interface_count: int = Field(ge=0, le=32)
    active_problem_count: int = Field(ge=0, le=1000)
    problems: list[AIZabbixHostProblemEvidence] = Field(default_factory=list, max_length=5)
    cpu_used_percent: float | None = Field(default=None, ge=0, le=100)
    memory_used_percent: float | None = Field(default=None, ge=0, le=100)
    peak_disk_used_percent: float | None = Field(default=None, ge=0, le=100)


class AIQuestionClassification(BaseModel):
    """Deterministic routing decision for an interactive AI question."""

    model_config = ConfigDict(extra="forbid")

    scope: AIQuestionScope
    source: IntegrationSource | None = None
    device_id: int | None = Field(default=None, gt=0)
    device_match_count: int = Field(default=0, ge=0, le=3)

    @model_validator(mode="after")
    def validate_scope_fields(self) -> "AIQuestionClassification":
        if self.scope == "environment":
            if self.source is not None or self.device_id is not None or self.device_match_count:
                raise ValueError("environment classification cannot contain source/device fields")
        elif self.scope == "source":
            if self.source is None or self.device_id is not None or self.device_match_count:
                raise ValueError("source classification requires exactly one source")
        else:
            if self.device_match_count < 1:
                raise ValueError("device classification requires a device match")
            if self.device_match_count == 1 and self.device_id is None:
                raise ValueError("unique device classification requires device_id")
            if self.device_match_count > 1 and self.device_id is not None:
                raise ValueError("ambiguous device classification cannot contain device_id")
        return self


class AIInvestigationEvidence(BaseModel):
    """Bounded normalized evidence selected for one interactive investigation."""

    model_config = ConfigDict(extra="forbid")

    observed_at: datetime
    range_start: datetime
    range_end: datetime
    classification: AIQuestionClassification
    sources: list[AISourceEvidence] = Field(default_factory=list, max_length=4)
    device: AICorrelatedDeviceEvidence | None = None
    freshservice_tickets: AIFreshserviceTicketSetEvidence | None = None
    snipe_it_assets: AISnipeItAssetSetEvidence | None = None
    wazuh_details: AIWazuhDetailEvidence | None = None
    zabbix_host: AIZabbixHostEvidence | None = None
    limitations: list[BoundedListText] = Field(default_factory=list, max_length=8)


class AIQueryResponse(BaseModel):
    """Application-controlled envelope around validated model output."""

    model_config = ConfigDict(extra="forbid")

    observed_at: datetime
    range_start: datetime
    range_end: datetime
    analysis: AIAnalysis
    source_warnings: list[BoundedListText] = Field(default_factory=list, max_length=12)


class AIDashboardSummaryResponse(BaseModel):
    """One cached payload containing the five Grafana AI summary sections."""

    model_config = ConfigDict(extra="forbid")

    observed_at: datetime
    range_start: datetime
    range_end: datetime
    executive: AIAnalysis
    wazuh: AIAnalysis
    zabbix: AIAnalysis
    snipe_it: AIAnalysis
    freshservice: AIAnalysis


class AIInvestigationResponse(BaseModel):
    """Application-grounded response for a classified interactive investigation."""

    model_config = ConfigDict(extra="forbid")

    observed_at: datetime
    range_start: datetime
    range_end: datetime
    classification: AIQuestionClassification
    device: AICorrelatedDeviceEvidence | None = None
    analysis: AIAnalysis
    source_warnings: list[BoundedListText] = Field(default_factory=list, max_length=12)
