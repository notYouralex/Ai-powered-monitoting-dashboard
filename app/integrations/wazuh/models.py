from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


WazuhAgentStatus = Literal[
    "active",
    "pending",
    "never_connected",
    "disconnected",
    "unknown",
]


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
