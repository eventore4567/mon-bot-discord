"""Dashboard view models. They deliberately expose runtime health limitations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EnvironmentDashboard:
    environment_id: str
    runtime_mode: str
    health: str
    identify_remaining: int | None
    identify_total: int | None
    can_redeploy: bool = True
    can_rollback: bool = True

    @property
    def health_level(self) -> str:
        if self.runtime_mode == "managed":
            return "Managed: Gateway + process health"
        if self.runtime_mode == "generic":
            return "Generic: process/log/REST health only"
        raise ValueError("invalid runtime mode")

    def as_dict(self) -> dict[str, object]:
        return {
            "environment_id": self.environment_id,
            "runtime_mode": self.runtime_mode,
            "health_level": self.health_level,
            "health": self.health,
            "identify_budget": {
                "remaining": self.identify_remaining,
                "total": self.identify_total,
            },
            "actions": {
                "restart": True,
                "redeploy": self.can_redeploy,
                "rollback": self.can_rollback,
            },
        }
