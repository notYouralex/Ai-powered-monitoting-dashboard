from datetime import datetime
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
    limitations: list[BoundedListText] = Field(default_factory=list, max_length=6)


class AIQueryResponse(BaseModel):
    """Application-controlled envelope around validated model output."""

    model_config = ConfigDict(extra="forbid")

    observed_at: datetime
    range_start: datetime
    range_end: datetime
    analysis: AIAnalysis
    source_warnings: list[BoundedListText] = Field(default_factory=list, max_length=12)


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
