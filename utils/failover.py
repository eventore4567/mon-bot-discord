"""Coordination active/passive stricte pour SentriX sur Railway.

Cette couche est volontairement *fail-closed* : quand le mode HA est activé, une
instance qui ne peut pas prouver qu'elle possède le lease Redis ne se connecte jamais
à Discord. Cela évite le split-brain (deux SentriX actifs qui répondent à la même
commande).

Le lease ne remplace pas le stockage durable. Le launcher HA restaure le dernier
snapshot PostgreSQL avant qu'une instance de secours devienne active.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
import uuid
from dataclasses import dataclass
from typing import Any

from utils.instance_identity import railway_service_name, storage_key

logger = logging.getLogger("bot.failover")

try:
    import redis.asyncio as redis_async  # type: ignore
except Exception:  # pragma: no cover - dépendance contrôlée au déploiement
    redis_async = None


class FailoverConfigurationError(RuntimeError):
    """Configuration HA invalide : le bot ne doit pas démarrer en mode dégradé."""


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on", "oui"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class LeadershipGrant:
    waited_seconds: float
    acquired_immediately: bool


class SentriXFailoverCoordinator:
    """Élection d'une seule instance Discord active avec un lease Redis à TTL."""

    _RENEW_SCRIPT = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
        return redis.call('expire', KEYS[1], ARGV[2])
    end
    return 0
    """

    _RELEASE_SCRIPT = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
        return redis.call('del', KEYS[1])
    end
    return 0
    """

    def __init__(self) -> None:
        self.enabled = _truthy("SENTRIX_FAILOVER_ENABLED", False)
        self.redis_url = (
            os.getenv("SENTRIX_FAILOVER_REDIS_URL")
            or os.getenv("SENTRIX_REDIS_URL")
            or os.getenv("REDIS_URL")
            or ""
        ).strip()
        self.ttl_seconds = _env_int("SENTRIX_FAILOVER_TTL", 30, 15, 180)
        self.renew_seconds = _env_int(
            "SENTRIX_FAILOVER_RENEW_INTERVAL",
            max(5, self.ttl_seconds // 4),
            3,
            max(3, self.ttl_seconds // 2),
        )
        self.poll_seconds = _env_int("SENTRIX_FAILOVER_POLL_INTERVAL", 2, 1, 30)

        configured_role = (os.getenv("SENTRIX_FAILOVER_ROLE") or "auto").strip().casefold()
        if configured_role not in {"auto", "primary", "standby"}:
            raise FailoverConfigurationError(
                "SENTRIX_FAILOVER_ROLE doit valoir auto, primary ou standby."
            )
        service_name = railway_service_name().casefold()
        self.role = (
            ("standby" if "standby" in service_name or "backup" in service_name else "primary")
            if configured_role == "auto"
            else configured_role
        )

        lock_name = (os.getenv("SENTRIX_FAILOVER_LOCK_NAME") or "failover:discord-primary").strip()
        self.lock_key = storage_key(lock_name)
        # Mémoire du dernier leader, indépendante du lease (qui expire, lui).
        # Elle permet de distinguer « je reprends la main après MON propre
        # redémarrage » (données locales encore valables) de « une autre instance
        # a écrit entre-temps » (restauration obligatoire).
        self.last_leader_key = storage_key(f"{lock_name}:last-leader")
        # Identité STABLE d'un redémarrage à l'autre, contrairement à owner_id qui
        # contient un uuid régénéré à chaque boot.
        self.service_id = (railway_service_name() or "local").casefold()

        replica_bits = [
            railway_service_name() or "local",
            os.getenv("RAILWAY_REPLICA_ID") or "",
            os.getenv("RAILWAY_DEPLOYMENT_ID") or "",
            socket.gethostname(),
            str(os.getpid()),
            uuid.uuid4().hex[:10],
        ]
        self.owner_id = ":".join(bit for bit in replica_bits if bit)[:220]

        self.state = "disabled" if not self.enabled else "starting"
        self.current_owner: str | None = None
        self.last_error: str | None = None
        self.leader_since: float | None = None

        self._redis: Any = None
        self._watchdog_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        # Service qui détenait le leadership juste AVANT nous (None si inconnu).
        self._dernier_leader_lu: str | None = None

    @property
    def is_leader(self) -> bool:
        return self.enabled and self.state == "leader"

    async def _connect(self) -> None:
        if not self.enabled:
            return
        if not self.redis_url:
            raise FailoverConfigurationError(
                "SENTRIX_FAILOVER_ENABLED=1 mais aucune URL Redis n'est configurée."
            )
        if redis_async is None:
            raise FailoverConfigurationError(
                "Le paquet redis.asyncio est indisponible alors que le failover est activé."
            )
        if self._redis is not None:
            return

        client = redis_async.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=10,
        )
        try:
            await client.ping()
        except Exception:
            try:
                await client.aclose()
            except Exception:
                pass
            raise
        self._redis = client

    async def _drop_client(self) -> None:
        client, self._redis = self._redis, None
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass

    async def _lire_dernier_leader(self) -> str | None:
        """Service qui détenait le leadership avant nous. Jamais bloquant."""
        try:
            valeur = await self._redis.get(self.last_leader_key)
        except Exception:
            return None
        return str(valeur).casefold() if valeur else None

    async def _marquer_dernier_leader(self) -> None:
        """Inscrit notre identité de service. Un échec ne doit pas coûter le leadership."""
        try:
            await self._redis.set(self.last_leader_key, self.service_id)
        except Exception:
            logger.warning("HA: mémorisation du dernier leader impossible (sans gravité).")

    def reprise_de_soi(self) -> bool:
        """Vrai si NOUS étions déjà le dernier leader avant ce démarrage.

        Dans ce cas le volume SQLite local est la copie la plus à jour : restaurer
        un snapshot ferait REVENIR EN ARRIÈRE les écritures faites depuis le dernier
        snapshot périodique. C'est précisément le cas d'un simple redéploiement du
        primary, le plus fréquent — et le plus coûteux si on restaure pour rien.
        """
        return self._dernier_leader_lu is not None and self._dernier_leader_lu == self.service_id

    def demander_arret(self) -> None:
        """Débloque ``wait_for_leadership()`` sur une instance encore passive.

        Sans cela, une instance qui attend le lease ignore SIGTERM : elle est tuée
        par SIGKILL à la fin du délai de grâce, sans dérouler ses ``finally``.
        """
        self._stop.set()

    async def _try_acquire(self) -> bool:
        await self._connect()
        acquired = await self._redis.set(
            self.lock_key,
            self.owner_id,
            nx=True,
            ex=self.ttl_seconds,
        )
        if acquired:
            self.state = "leader"
            self.current_owner = self.owner_id
            self.last_error = None
            self.leader_since = time.monotonic()
            self._dernier_leader_lu = await self._lire_dernier_leader()
            await self._marquer_dernier_leader()
            logger.warning(
                "HA: leadership acquis role=%s lease=%ss owner=%s",
                self.role,
                self.ttl_seconds,
                self.owner_id,
            )
            return True

        self.current_owner = await self._redis.get(self.lock_key)
        self.state = "standby"
        return False

    async def wait_for_leadership(self) -> LeadershipGrant:
        """Attend le lease sans jamais ouvrir Discord en absence de preuve de leadership."""
        if not self.enabled:
            return LeadershipGrant(waited_seconds=0.0, acquired_immediately=True)

        started = time.monotonic()
        first_attempt = True
        while not self._stop.is_set():
            try:
                if await self._try_acquire():
                    waited = max(0.0, time.monotonic() - started)
                    return LeadershipGrant(
                        waited_seconds=waited,
                        acquired_immediately=first_attempt and waited < 2.5,
                    )
            except FailoverConfigurationError:
                self.state = "error"
                raise
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.state = "blocked"
                self.current_owner = None
                self.last_error = f"{type(exc).__name__}: {exc}"[:500]
                logger.warning("HA: Redis indisponible, SentriX reste en attente: %s", self.last_error)
                await self._drop_client()

            first_attempt = False
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                pass

        raise asyncio.CancelledError

    async def _renew_once(self) -> bool:
        await self._connect()
        result = await self._redis.eval(
            self._RENEW_SCRIPT,
            1,
            self.lock_key,
            self.owner_id,
            self.ttl_seconds,
        )
        return bool(int(result or 0))

    async def _watch_leadership(self, bot: Any) -> None:
        """Fence immédiatement l'instance si son lease n'est plus renouvelable."""
        try:
            while not self._stop.is_set() and self.state == "leader":
                await asyncio.sleep(self.renew_seconds)
                try:
                    renewed = await self._renew_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.last_error = f"{type(exc).__name__}: {exc}"[:500]
                    renewed = False

                if renewed:
                    continue

                self.state = "lost"
                self.current_owner = None
                logger.critical(
                    "HA: lease perdu ou Redis inaccessible. Fermeture Discord immédiate pour "
                    "éviter un split-brain. erreur=%s",
                    self.last_error,
                )
                try:
                    await bot.close()
                except Exception:
                    logger.exception("HA: fermeture Discord après perte du lease impossible.")
                return
        except asyncio.CancelledError:
            return

    def start_watchdog(self, bot: Any) -> asyncio.Task | None:
        if not self.enabled:
            return None
        if not self.is_leader:
            raise RuntimeError("Impossible de démarrer le watchdog HA sans leadership.")
        if self._watchdog_task is None or self._watchdog_task.done():
            self._watchdog_task = asyncio.create_task(
                self._watch_leadership(bot),
                name="sentrix-ha-lease-watchdog",
            )
        return self._watchdog_task

    async def release(self) -> bool:
        if not self.enabled or self._redis is None or self.state != "leader":
            return False
        try:
            result = await self._redis.eval(
                self._RELEASE_SCRIPT,
                1,
                self.lock_key,
                self.owner_id,
            )
            released = bool(int(result or 0))
            if released:
                self.state = "released"
                self.current_owner = None
                logger.info("HA: lease libéré proprement.")
            return released
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"[:500]
            logger.warning("HA: libération du lease impossible, expiration TTL attendue.")
            return False

    async def close(self, *, release: bool = True) -> None:
        self._stop.set()
        task, self._watchdog_task = self._watchdog_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        if release:
            await self.release()
        await self._drop_client()

    def health(self) -> dict[str, Any]:
        leader_for = None
        if self.leader_since is not None and self.state == "leader":
            leader_for = round(max(0.0, time.monotonic() - self.leader_since), 1)
        return {
            "enabled": self.enabled,
            "state": self.state,
            "role": self.role,
            "leader": self.is_leader,
            "lock_key": self.lock_key if self.enabled else None,
            "owner": self.owner_id if self.enabled else None,
            "current_owner": self.current_owner,
            "ttl_seconds": self.ttl_seconds if self.enabled else None,
            "renew_seconds": self.renew_seconds if self.enabled else None,
            "leader_for_seconds": leader_for,
            "error": self.last_error,
        }
