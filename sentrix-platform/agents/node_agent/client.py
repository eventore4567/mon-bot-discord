"""Client HTTP pull/report du node-agent."""

from __future__ import annotations

from uuid import UUID

import httpx

from libs.runtime_models import AgentDesiredInstance, AgentObservedInstance, AgentReport


class ControlPlaneClient:
    def __init__(self, base_url: str, node_id: UUID, token: str) -> None:
        self._base = base_url.rstrip("/")
        self._node_id = node_id
        self._headers = {"X-Sentrix-Node-Token": token}
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))

    async def pull(self) -> list[AgentDesiredInstance]:
        response = await self._client.get(
            f"{self._base}/v1/agent/nodes/{self._node_id}/desired",
            headers=self._headers,
        )
        response.raise_for_status()
        return [AgentDesiredInstance.model_validate(item) for item in response.json()]

    async def report(self, statuses: list[AgentObservedInstance]) -> None:
        payload = AgentReport(statuses=statuses)
        response = await self._client.post(
            f"{self._base}/v1/agent/nodes/{self._node_id}/report",
            headers=self._headers,
            json=payload.model_dump(mode="json"),
        )
        response.raise_for_status()

    async def close(self) -> None:
        await self._client.aclose()
