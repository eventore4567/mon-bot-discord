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
    async def heartbeat(self, node_id: UUID, payload: dict[str, object], *, ttl: int = 30) -> None: ...

    async def close(self) -> None: ...


class RedisStatusStore:
    def __init__(self, redis_url: str) -> None:
        from redis.asyncio import Redis

        self._redis = Redis.from_url(redis_url, decode_responses=True)

    async def heartbeat(self, node_id: UUID, payload: dict[str, object], *, ttl: int = 30) -> None:
        key = f"sentrix:node:{node_id}:heartbeat"
        await self._redis.set(key, json.dumps(payload, separators=(",", ":")), ex=ttl)

    async def close(self) -> None:
        await self._redis.aclose()


@dataclass
class MemoryStatusStore:
    """Double de test, jamais utilise comme stockage de production."""

    heartbeats: dict[UUID, dict[str, object]] = field(default_factory=dict)

    async def heartbeat(self, node_id: UUID, payload: dict[str, object], *, ttl: int = 30) -> None:
        del ttl
        self.heartbeats[node_id] = dict(payload)

    async def close(self) -> None:
        return None
