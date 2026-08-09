"""Infrastructure distribuée optionnelle de SentriX.

Le bot continue à fonctionner sans service externe. Quand Railway fournit DATABASE_URL /
POSTGRES_URL et/ou REDIS_URL, cette couche active automatiquement :
- un pool PostgreSQL pour les événements/mesures enterprise ;
- Redis pour compteurs inter-shards, verrous courts et invalidation de cache.

SQLite reste le fallback historique afin qu'un service absent ne puisse jamais empêcher
SentriX de démarrer. Aucun secret n'est journalisé.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("bot.enterprise.infra")

try:
    import asyncpg  # type: ignore
except Exception:  # pragma: no cover - dépendance optionnelle au runtime
    asyncpg = None

try:
    import redis.asyncio as redis_async  # type: ignore
except Exception:  # pragma: no cover - dépendance optionnelle au runtime
    redis_async = None


class EnterpriseInfra:
    def __init__(self) -> None:
        self.postgres_url = (os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL") or "").strip()
        self.redis_url = (os.getenv("REDIS_URL") or "").strip()
        self.pg_pool = None
        self.redis = None
        self.postgres_error: str | None = None
        self.redis_error: str | None = None

    async def connect(self) -> None:
        if self.postgres_url and asyncpg is not None:
            try:
                self.pg_pool = await asyncpg.create_pool(
                    self.postgres_url,
                    min_size=1,
                    max_size=max(2, int(os.getenv("POSTGRES_POOL_MAX", "8"))),
                    command_timeout=20,
                )
                async with self.pg_pool.acquire() as conn:
                    await conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS sentrix_enterprise_events (
                            id BIGSERIAL PRIMARY KEY,
                            event_type TEXT NOT NULL,
                            guild_id BIGINT,
                            payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                            created_at BIGINT NOT NULL
                        );
                        CREATE INDEX IF NOT EXISTS idx_sentrix_enterprise_events_guild_time
                        ON sentrix_enterprise_events (guild_id, created_at DESC);
                        CREATE TABLE IF NOT EXISTS sentrix_enterprise_metrics (
                            id BIGSERIAL PRIMARY KEY,
                            metric_name TEXT NOT NULL,
                            guild_id BIGINT,
                            value DOUBLE PRECISION NOT NULL,
                            labels_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                            created_at BIGINT NOT NULL
                        );
                        CREATE INDEX IF NOT EXISTS idx_sentrix_enterprise_metrics_name_time
                        ON sentrix_enterprise_metrics (metric_name, created_at DESC);
                        """
                    )
                logger.info("PostgreSQL enterprise connecté.")
            except Exception as exc:
                self.postgres_error = f"{type(exc).__name__}: {exc}"[:500]
                self.pg_pool = None
                logger.warning("PostgreSQL enterprise indisponible ; fallback SQLite conservé.")
        elif self.postgres_url:
            self.postgres_error = "asyncpg indisponible"

        if self.redis_url and redis_async is not None:
            try:
                self.redis = redis_async.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                )
                await self.redis.ping()
                logger.info("Redis enterprise connecté.")
            except Exception as exc:
                self.redis_error = f"{type(exc).__name__}: {exc}"[:500]
                self.redis = None
                logger.warning("Redis enterprise indisponible ; caches locaux conservés.")
        elif self.redis_url:
            self.redis_error = "redis-py indisponible"

    async def close(self) -> None:
        if self.redis is not None:
            try:
                await self.redis.aclose()
            except Exception:
                pass
        if self.pg_pool is not None:
            try:
                await self.pg_pool.close()
            except Exception:
                pass

    async def incr(self, key: str, amount: int = 1, *, ttl: int = 120) -> int | None:
        if self.redis is None:
            return None
        redis_key = f"sentrix:{key}"[:240]
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.incrby(redis_key, int(amount))
                pipe.expire(redis_key, max(5, int(ttl)))
                result = await pipe.execute()
            return int(result[0])
        except Exception:
            return None

    async def get_counter(self, key: str) -> int | None:
        if self.redis is None:
            return None
        try:
            value = await self.redis.get(f"sentrix:{key}"[:240])
            return int(value) if value is not None else 0
        except Exception:
            return None

    async def acquire_lease(self, name: str, value: str, *, ttl: int = 60) -> bool:
        """Verrou distribué court. Retourne False si un autre shard détient déjà le lease."""
        if self.redis is None:
            return True
        try:
            return bool(await self.redis.set(f"sentrix:lease:{name}"[:240], value, ex=max(5, ttl), nx=True))
        except Exception:
            return True

    async def release_lease(self, name: str, value: str) -> None:
        if self.redis is None:
            return
        key = f"sentrix:lease:{name}"[:240]
        # Compare-and-delete atomique afin de ne jamais retirer le lease d'un autre shard.
        script = "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end"
        try:
            await self.redis.eval(script, 1, key, value)
        except Exception:
            pass

    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        if self.redis is None:
            return
        try:
            await self.redis.publish(f"sentrix:{channel}"[:180], json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        except Exception:
            pass

    async def mirror_event(self, event_type: str, guild_id: int | None, payload: dict[str, Any], created_at: int) -> None:
        if self.pg_pool is None:
            return
        try:
            await self.pg_pool.execute(
                "INSERT INTO sentrix_enterprise_events (event_type, guild_id, payload_json, created_at) VALUES ($1,$2,$3::jsonb,$4)",
                str(event_type)[:120], guild_id, json.dumps(payload, ensure_ascii=False), int(created_at),
            )
        except Exception:
            pass

    async def mirror_metric(self, name: str, guild_id: int | None, value: float, labels: dict[str, Any], created_at: int) -> None:
        if self.pg_pool is None:
            return
        try:
            await self.pg_pool.execute(
                "INSERT INTO sentrix_enterprise_metrics (metric_name, guild_id, value, labels_json, created_at) VALUES ($1,$2,$3,$4::jsonb,$5)",
                str(name)[:120], guild_id, float(value), json.dumps(labels, ensure_ascii=False), int(created_at),
            )
        except Exception:
            pass

    async def health(self) -> dict[str, Any]:
        pg_ok = False
        redis_ok = False
        if self.pg_pool is not None:
            try:
                pg_ok = bool(await self.pg_pool.fetchval("SELECT 1"))
            except Exception:
                pg_ok = False
        if self.redis is not None:
            try:
                redis_ok = bool(await self.redis.ping())
            except Exception:
                redis_ok = False
        return {
            "postgres_configured": bool(self.postgres_url),
            "postgres_online": pg_ok,
            "postgres_error": self.postgres_error if not pg_ok else None,
            "redis_configured": bool(self.redis_url),
            "redis_online": redis_ok,
            "redis_error": self.redis_error if not redis_ok else None,
        }
