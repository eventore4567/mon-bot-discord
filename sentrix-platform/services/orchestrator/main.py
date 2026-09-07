"""Entrypoint for the SentriX deployment orchestrator.

The orchestrator has no Docker socket and no tenant database credentials. It
advances one durable deployment step at a time through the private control API.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from uuid import UUID

import httpx
from pydantic import BaseModel


class TickResult(BaseModel):
    deployment_id: UUID
    deployment_status: str
    deployment_step: str
    detail: str


@dataclass(frozen=True, slots=True)
class OrchestratorConfig:
    api_url: str
    worker_id: UUID
    worker_token: str
    idle_poll_seconds: float = 2.0
    active_poll_seconds: float = 1.0

    @classmethod
    def from_env(cls) -> OrchestratorConfig:
        api_url = os.environ["SENTRIX_API_URL"].rstrip("/")
        if not api_url.startswith(("https://", "http://")):
            raise RuntimeError("SENTRIX_API_URL must be http(s)")
        return cls(
            api_url=api_url,
            worker_id=UUID(os.environ["SENTRIX_CONTROL_WORKER_ID"]),
            worker_token=os.environ["SENTRIX_CONTROL_WORKER_TOKEN"],
            idle_poll_seconds=float(os.environ.get("SENTRIX_ORCH_IDLE_POLL", "2")),
            active_poll_seconds=float(os.environ.get("SENTRIX_ORCH_ACTIVE_POLL", "1")),
        )


async def run_orchestrator(config: OrchestratorConfig) -> None:
    headers = {
        "X-Sentrix-Worker-Id": str(config.worker_id),
        "X-Sentrix-Worker-Token": config.worker_token,
    }
    async with httpx.AsyncClient(
        base_url=config.api_url,
        headers=headers,
        timeout=httpx.Timeout(30.0),
    ) as client:
        while True:
            response = await client.post("/v1/control/orchestrator/tick")
            response.raise_for_status()
            if response.content in (b"", b"null"):
                await asyncio.sleep(config.idle_poll_seconds)
                continue
            result = TickResult.model_validate(response.json())
            delay = (
                config.active_poll_seconds
                if result.deployment_status == "running"
                else config.idle_poll_seconds
            )
            await asyncio.sleep(delay)


def main() -> None:
    asyncio.run(run_orchestrator(OrchestratorConfig.from_env()))


if __name__ == "__main__":
    main()
