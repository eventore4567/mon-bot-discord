"""Election active/passive Redis pour les deux runtimes SentriX.

Le service de secours ne se connecte jamais a Discord tant qu'un autre processus
detient le lease. Le lease est renouvele par compare-and-expire atomique et le runtime
actif se ferme avant l'expiration si Redis ne confirme plus son autorite. Cela evite le
split-brain (deux bots qui repondent ou moderent le meme evenement).
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from utils.instance_identity import storage_key

logger = logging.getLogger("bot.failover")

try:
    import redis.asyncio as redis_async  # type: ignore
except Exception:  # pragma: no cover - dependance runtime optionnelle
    redis_async = None


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on", "oui"}


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class FailoverSettings:
    enabled: bool
    role: str
    lease_ttl: int
    renew_interval: int
    poll_interval: int
    standby_delay: int
    snapshot_interval: int

    @classmethod
    def from_env(cls) -> FailoverSettings:
        enabled = _truthy("SENTRIX_FAILOVER_ENABLED", False)
        role = (os.getenv("SENTRIX_FAILOVER_ROLE") or "auto").strip().casefold()
        if role not in {"primary", "standby", "auto"}:
            role = "auto"
        lease_ttl = _bounded_int("SENTRIX_FAILOVER_LEASE_TTL", 20, 12, 120)
        renew_default = max(3, lease_ttl // 4)
        renew_interval = _bounded_int(
            "SENTRIX_FAILOVER_RENEW_INTERVAL", renew_default, 2, max(2, lease_ttl // 3)
        )
        return cls(
            enabled=enabled,
            role=role,
            lease_ttl=lease_ttl,
            renew_interval=renew_interval,
            poll_interval=_bounded_int("SENTRIX_FAILOVER_POLL_INTERVAL", 3, 1, 30),
            standby_delay=_bounded_int("SENTRIX_FAILOVER_STANDBY_DELAY", 8, 0, 60),
            snapshot_interval=_bounded_int("SENTRIX_FAILOVER_SNAPSHOT_INTERVAL", 30, 10, 300),
        )


_ACTIVE_COORDINATOR: RedisFailoverLease | None = None


def install_active_coordinator(coordinator: RedisFailoverLease | None) -> None:
    global _ACTIVE_COORDINATOR
    _ACTIVE_COORDINATOR = coordinator


def is_active_process() -> bool:
    """Autorite runtime partagee par les logs, l'IA et les mutations uniques."""
    settings = FailoverSettings.from_env()
    if not settings.enabled:
        return True
    return bool(_ACTIVE_COORDINATOR and _ACTIVE_COORDINATOR.owns_lease)


class RedisFailoverLease:
    """Lease Redis exclusif avec watchdog anti split-brain."""

    _RENEW_SCRIPT = (
        "if redis.call('get',KEYS[1])==ARGV[1] then "
        "return redis.call('expire',KEYS[1],ARGV[2]) else return 0 end"
    )
    _RELEASE_SCRIPT = (
        "if redis.call('get',KEYS[1])==ARGV[1] then "
        "return redis.call('del',KEYS[1]) else return 0 end"
    )

    def __init__(self, settings: FailoverSettings, *, redis_client=None) -> None:
        self.settings = settings
        self.redis_url = (os.getenv("REDIS_URL") or "").strip()
        process_hint = (
            os.getenv("RAILWAY_REPLICA_ID")
            or os.getenv("RAILWAY_DEPLOYMENT_ID")
            or os.getenv("RAILWAY_SERVICE_ID")
            or socket.gethostname()
            or "local"
        )
        self.holder_id = f"{str(process_hint)[:80]}:{uuid.uuid4().hex}"
        self.key = storage_key("failover:active")
        self.redis = redis_client
        self.owns_lease = False
        self.status = "initializing"
        self.last_acquired_at: int | None = None
        self.last_renewed_at: int | None = None
        self.last_error: str | None = None
        self.last_snapshot_at: int | None = None
        self.last_snapshot_id: int | None = None

    async def connect(self) -> None:
        if self.redis is not None:
            await self.redis.ping()
            self.status = "candidate"
            return
        if not self.redis_url:
            raise RuntimeError("SENTRIX_FAILOVER_ENABLED exige REDIS_URL.")
        if redis_async is None:
            raise RuntimeError("SENTRIX_FAILOVER_ENABLED exige le paquet redis.")
        self.redis = redis_async.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=15,
        )
        await self.redis.ping()
        self.status = "candidate"

    async def try_acquire(self) -> bool:
        if self.redis is None:
            raise RuntimeError("Redis failover non connecte.")
        try:
            acquired = bool(
                await self.redis.set(
                    self.key,
                    self.holder_id,
                    ex=self.settings.lease_ttl,
                    nx=True,
                )
            )
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"[:300]
            self.status = "redis_error"
            return False
        if acquired:
            now = int(time.time())
            self.owns_lease = True
            self.status = "active"
            self.last_acquired_at = now
            self.last_renewed_at = now
            self.last_error = None
            install_active_coordinator(self)
            logger.warning("Lease failover acquis; ce processus devient SentriX actif.")
            return True
        self.owns_lease = False
        self.status = "standby"
        return False

    async def renew(self) -> bool | None:
        """True=renouvele, False=lease perdu, None=Redis injoignable."""
        if self.redis is None or not self.owns_lease:
            return False
        try:
            renewed = bool(
                await self.redis.eval(
                    self._RENEW_SCRIPT,
                    1,
                    self.key,
                    self.holder_id,
                    self.settings.lease_ttl,
                )
            )
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"[:300]
            self.status = "redis_unconfirmed"
            return None
        if renewed:
            self.last_renewed_at = int(time.time())
            self.last_error = None
            self.status = "active"
            return True
        self.owns_lease = False
        self.status = "lease_lost"
        install_active_coordinator(None)
        return False

    async def maintain(self, on_lost: Callable[[], Awaitable[None]]) -> None:
        """Renouvelle le lease et coupe Discord avant qu'un autre noeud puisse agir."""
        last_confirmed = time.monotonic()
        while self.owns_lease:
            await asyncio.sleep(self.settings.renew_interval)
            result = await self.renew()
            if result is True:
                last_confirmed = time.monotonic()
                continue
            if result is False:
                logger.critical("Lease failover perdu; fermeture immediate de Discord.")
                await on_lost()
                return
            # En cas de panne Redis, le processus actif ne reste jamais connecte jusqu'a
            # l'expiration possible du verrou. Il se retire une seconde avant au plus tard.
            if time.monotonic() - last_confirmed >= self.settings.lease_ttl - 1:
                self.owns_lease = False
                self.status = "lease_unconfirmed"
                install_active_coordinator(None)
                logger.critical("Lease non confirme avant expiration; fermeture anti split-brain.")
                await on_lost()
                return

    def record_snapshot(self, result: dict) -> None:
        if result.get("stored"):
            self.last_snapshot_at = int(result.get("created_at") or time.time())
            snapshot_id = result.get("snapshot_id")
            self.last_snapshot_id = int(snapshot_id) if snapshot_id is not None else None

    def public_state(self) -> dict[str, object]:
        return {
            "enabled": self.settings.enabled,
            "role": self.settings.role,
            "status": self.status,
            "active": self.owns_lease,
            "lease_ttl_seconds": self.settings.lease_ttl,
            "renew_interval_seconds": self.settings.renew_interval,
            "last_acquired_at": self.last_acquired_at,
            "last_renewed_at": self.last_renewed_at,
            "last_snapshot_at": self.last_snapshot_at,
            "last_snapshot_id": self.last_snapshot_id,
            "last_error": self.last_error,
        }

    async def release(self) -> None:
        owned = self.owns_lease
        self.owns_lease = False
        self.status = "stopped"
        install_active_coordinator(None)
        if not owned or self.redis is None:
            return
        try:
            await self.redis.eval(self._RELEASE_SCRIPT, 1, self.key, self.holder_id)
        except Exception:
            logger.warning("Liberation du lease failover impossible; le TTL prendra le relais.")

    async def close(self) -> None:
        await self.release()
        redis, self.redis = self.redis, None
        if redis is not None and hasattr(redis, "aclose"):
            try:
                await redis.aclose()
            except Exception:
                pass


__all__ = [
    "FailoverSettings",
    "RedisFailoverLease",
    "install_active_coordinator",
    "is_active_process",
]
