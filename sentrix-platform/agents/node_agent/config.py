"""Configuration stricte du node-agent."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID


@dataclass(frozen=True)
class AgentConfig:
    control_plane_url: str
    node_id: UUID
    node_token: str
    cache_path: Path
    poll_seconds: float = 5.0
    docker_bin: str = "docker"
    runtime: str = "runsc"
    egress_script: Path = Path("ops/execution/apply-egress-policy.sh")
    control_plane_cidrs: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> AgentConfig:
        token = os.environ["SENTRIX_NODE_TOKEN"]
        if len(token) < 16:
            raise RuntimeError("SENTRIX_NODE_TOKEN doit contenir au moins 16 caracteres")
        runtime = os.environ.get("SENTRIX_SANDBOX_RUNTIME", "runsc")
        if runtime != "runsc":
            raise RuntimeError("P1 exige le runtime gVisor 'runsc'")
        cidrs = tuple(
            value.strip()
            for value in os.environ.get("SENTRIX_CONTROL_PLANE_CIDRS", "").split(",")
            if value.strip()
        )
        return cls(
            control_plane_url=os.environ["SENTRIX_CONTROL_PLANE_URL"].rstrip("/"),
            node_id=UUID(os.environ["SENTRIX_NODE_ID"]),
            node_token=token,
            cache_path=Path(
                os.environ.get("SENTRIX_AGENT_CACHE", "/var/lib/sentrix-agent/desired.json")
            ),
            poll_seconds=float(os.environ.get("SENTRIX_AGENT_POLL_SECONDS", "5")),
            docker_bin=os.environ.get("SENTRIX_DOCKER_BIN", "docker"),
            runtime=runtime,
            egress_script=Path(
                os.environ.get("SENTRIX_EGRESS_SCRIPT", "ops/execution/apply-egress-policy.sh")
            ),
            control_plane_cidrs=cidrs,
        )
