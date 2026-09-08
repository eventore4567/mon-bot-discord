"""Stockage ephemere P1 pour heartbeat/sante courante.

Les heartbeats haute frequence vont dans Redis avec TTL. PostgreSQL ne recoit
que les transitions d'etat via sentrix_agent_report_instance().
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID


class StatusStore(Protocol):
    async def heartbeat(
        self, node_id: UUID, payload: dict[str, object], *, ttl: int = 30
    ) -> None: ...

    async def get_heartbeat(self, node_id: UUID) -> dict[str, object] | None: ...

    async def count_online_heartbeats(self) -> int: ...

    async def close(self) -> None: ...


class RedisStatusStore:
    def __init__(self, redis_url: str) -> None:
        from redis.asyncio import Redis

        self._redis = Redis.from_url(redis_url, decode_responses=True)

    @staticmethod
    def _key(node_id: UUID) -> str:
        return f"sentrix:node:{node_id}:heartbeat"

    async def heartbeat(self, node_id: UUID, payload: dict[str, object], *, ttl: int = 30) -> None:
        await self._redis.set(
            self._key(node_id),
            json.dumps(payload, separators=(",", ":")),
            ex=ttl,
        )

    async def get_heartbeat(self, node_id: UUID) -> dict[str, object] | None:
        raw = await self._redis.get(self._key(node_id))
        if raw is None:
            return None
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else None

    async def count_online_heartbeats(self) -> int:
        count = 0
        async for key in self._redis.scan_iter(match="sentrix:node:*:heartbeat", count=100):
            raw = await self._redis.get(key)
            if raw is None:
                continue
            try:
                payload = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and payload.get("status") == "online":
                count += 1
        return count

    async def close(self) -> None:
        await self._redis.aclose()


@dataclass
class MemoryStatusStore:
    """Double de test, jamais utilise comme stockage de production."""

    heartbeats: dict[UUID, dict[str, object]] = field(default_factory=dict)

    async def heartbeat(self, node_id: UUID, payload: dict[str, object], *, ttl: int = 30) -> None:
        del ttl
        self.heartbeats[node_id] = dict(payload)

    async def get_heartbeat(self, node_id: UUID) -> dict[str, object] | None:
        payload = self.heartbeats.get(node_id)
        return dict(payload) if payload is not None else None

    async def count_online_heartbeats(self) -> int:
        return sum(1 for payload in self.heartbeats.values() if payload.get("status") == "online")

    async def close(self) -> None:
        return None
