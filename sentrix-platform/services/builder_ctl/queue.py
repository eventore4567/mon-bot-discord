"""Reliable Redis Streams queue for SentriX build jobs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from redis.asyncio import Redis

_STREAM = "sentrix:builds:v1"
_GROUP = "sentrix-builders-v1"


@dataclass(frozen=True, slots=True)
class BuildJob:
    build_id: str
    org_id: str
    environment_id: str
    repository: str
    branch: str
    commit_sha: str


@dataclass(frozen=True, slots=True)
class ClaimedBuild:
    message_id: str
    job: BuildJob


class BuildQueue:
    def __init__(self, redis_url: str) -> None:
        self._redis = Redis.from_url(redis_url, decode_responses=True)

    async def close(self) -> None:
        await self._redis.aclose()

    async def _ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(_STREAM, _GROUP, id="0", mkstream=True)
        except Exception as exc:  # noqa: BLE001 - Redis uses ResponseError subtypes across versions.
            if "BUSYGROUP" not in str(exc):
                raise

    async def enqueue(self, job: BuildJob) -> str:
        await self._ensure_group()
        payload = json.dumps(asdict(job), separators=(",", ":"), sort_keys=True)
        result = await self._redis.xadd(_STREAM, {"payload": payload})
        return str(result)

    @staticmethod
    def _parse(message_id: object, fields: dict[str, Any]) -> ClaimedBuild:
        payload = fields.get("payload")
        if not isinstance(payload, str):
            raise ValueError("build queue payload absent")
        raw = json.loads(payload)
        if not isinstance(raw, dict):
            raise ValueError("build queue payload invalide")
        return ClaimedBuild(str(message_id), BuildJob(**raw))

    async def claim(self, worker_id: str, *, stale_ms: int = 60_000) -> ClaimedBuild | None:
        await self._ensure_group()

        # Reclaim a job abandoned by a dead builder before consuming new work.
        reclaimed = await self._redis.xautoclaim(
            _STREAM,
            _GROUP,
            worker_id,
            min_idle_time=stale_ms,
            start_id="0-0",
            count=1,
        )
        if isinstance(reclaimed, (list, tuple)) and len(reclaimed) >= 2:
            messages = reclaimed[1]
            if isinstance(messages, list) and messages:
                message_id, fields = messages[0]
                if isinstance(fields, dict):
                    return self._parse(message_id, fields)

        fresh = await self._redis.xreadgroup(
            _GROUP,
            worker_id,
            {_STREAM: ">"},
            count=1,
            block=1000,
        )
        if not fresh:
            return None
        _, messages = fresh[0]
        if not messages:
            return None
        message_id, fields = messages[0]
        return self._parse(message_id, fields)

    async def ack(self, message_id: str) -> None:
        await self._ensure_group()
        await self._redis.xack(_STREAM, _GROUP, message_id)
        await self._redis.xdel(_STREAM, message_id)
