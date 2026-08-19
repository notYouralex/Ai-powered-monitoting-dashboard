from datetime import datetime
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.contracts import IntegrationSource


CorrelationMatchMethod: TypeAlias = Literal[
    "manual",
    "serial",
    "asset_tag",
    "hostname",
    "stable_ip",
    "combined",
    "new_device",
    "existing_link",
]
AutomaticMatchMethod: TypeAlias = Literal[
    "serial",
    "asset_tag",
    "hostname",
    "stable_ip",
    "combined",
]


class DeviceObservation(BaseModel):
    """Normalized source evidence consumed by the shared correlation engine."""

    model_config = ConfigDict(extra="forbid")

    source: IntegrationSource
    source_record_id: str = Field(min_length=1, max_length=255)
    observed_at: datetime
    name: str | None = Field(default=None, max_length=255)
    hostname: str | None = Field(default=None, max_length=255)
    stable_ip: str | None = Field(default=None, max_length=64)
    serial: str | None = Field(default=None, max_length=255)
    asset_tag: str | None = Field(default=None, max_length=255)
    os: str | None = Field(default=None, max_length=255)
    device_type: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)

    @field_validator(
        "source_record_id",
        "name",
        "hostname",
        "stable_ip",
        "serial",
        "asset_tag",
        "os",
        "device_type",
        "location",
        mode="before",
    )
    @classmethod
    def strip_strings(cls, value):
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped or None


class CorrelationMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: AutomaticMatchMethod
    confidence: int = Field(ge=0, le=100)


class CorrelationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: IntegrationSource
    source_record_id: str = Field(min_length=1, max_length=255)
    device_id: int = Field(gt=0)
    method: CorrelationMatchMethod
    confidence: int = Field(ge=0, le=100)
    created_device: bool = False
    manual_override: bool = False
