"""Runtime-aware deployment planning (P4)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeploymentPlan:
    runtime_mode: str
    prewarm: str
    handover: str
    health_level: str


def plan_for(runtime_mode: str) -> DeploymentPlan:
    if runtime_mode == "managed":
        return DeploymentPlan("managed", "process-warm-gateway-held", "sequenced", "gateway-rich")
    if runtime_mode == "generic":
        return DeploymentPlan("generic", "image-network-only", "stop-start", "process-liveness")
    raise ValueError("unknown runtime mode")
