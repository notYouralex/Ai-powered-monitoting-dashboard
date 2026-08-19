from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts import IntegrationHealthSummary, IntegrationSource


INTEGRATION_HEALTH_SOURCES: tuple[IntegrationSource, ...] = (
    "wazuh",
    "zabbix",
    "snipe_it",
    "freshservice",
)


class IntegrationHealthResponse(BaseModel):
    """Bounded cross-source health response using canonical integration health contracts."""

    model_config = ConfigDict(extra="forbid")

    observed_at: datetime
    integrations: list[IntegrationHealthSummary] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def validate_integrations(self) -> "IntegrationHealthResponse":
        sources = [health.source for health in self.integrations]
        if sources != list(INTEGRATION_HEALTH_SOURCES):
            raise ValueError("integration health must contain each canonical source in order")
        return self
