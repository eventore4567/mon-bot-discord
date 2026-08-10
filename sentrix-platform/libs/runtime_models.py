"""Modeles P1 : etat desire et rapports du node-agent."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

DesiredState = Literal["running", "stopped"]
ObservedState = Literal["running", "stopped", "failed", "unknown"]
HealthState = Literal["healthy", "unhealthy", "unknown"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")


class InstanceCreate(_In):
    environment_id: UUID
    node_id: UUID
    image_ref: str = Field(min_length=1, max_length=512)
    command: list[str] = Field(default_factory=list, max_length=64)
    cpu_millis: int = Field(default=500, ge=50, le=16000)
    memory_mb: int = Field(default=256, ge=32, le=65536)
    pids_limit: int = Field(default=128, ge=16, le=4096)

    @field_validator("command")
    @classmethod
    def command_parts_are_bounded(cls, value: list[str]) -> list[str]:
        if any(not part or len(part) > 4096 for part in value):
            raise ValueError("chaque argument de commande doit contenir 1 a 4096 caracteres")
        return value


class InstanceDesiredUpdate(_In):
    desired_state: DesiredState


class InstanceOut(_Out):
    id: UUID
    org_id: UUID
    env_id: UUID
    cell_id: UUID
    node_id: UUID
    desired_state: str
    image_ref: str
    command: list[str]
    cpu_millis: int
    memory_mb: int
    pids_limit: int
    generation: int


class InstanceStatusOut(_Out):
    instance_id: UUID
    org_id: UUID
    observed_state: str
    container_id: str | None
    generation: int
    exit_code: int | None
    health: str
    detail: str | None


class AgentDesiredInstance(_Out):
    instance_id: UUID
    desired_state: DesiredState
    image_ref: str
    command: list[str]
    cpu_millis: int
    memory_mb: int
    pids_limit: int
    generation: int


class AgentObservedInstance(_In):
    instance_id: UUID
    observed_state: ObservedState
    container_id: str | None = Field(default=None, max_length=128)
    generation: int = Field(ge=0)
    exit_code: int | None = None
    health: HealthState = "unknown"
    detail: str | None = Field(default=None, max_length=2000)


class AgentReport(_In):
    statuses: list[AgentObservedInstance] = Field(default_factory=list, max_length=2048)
