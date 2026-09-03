"""Launcher Railway haute disponibilité pour SentriX.

Utilisation Railway (principal ET secours) :
    python railway_ha_boot.py

Le launcher garde `railway_boot.py` intact et ajoute quatre garanties :
1. une seule instance peut ouvrir la session Discord ;
2. le lease Redis est renouvelé en continu et la perte du lease ferme Discord ;
3. un secours restaure le dernier snapshot PostgreSQL avant de prendre la main ;
4. /health considère un standby HA comme un processus sain sans prétendre qu'il sert Discord.
"""
from __future__ import annotations

import asyncio
import logging
import os
import traceback
from typing import Any

from aiohttp import web as aiohttp_web
import discord


# Certains cogs historiques démarrent leurs tâches de fond dès leur construction et leur
# before_loop appelle wait_until_ready(). Sur une instance HA standby, ces tâches peuvent
# s'exécuter quelques millisecondes avant que le contexte asynchrone de discord.py ait créé
# son Event interne `_ready`. discord.py lève alors "Client has not been properly
# initialised" et les boucles meurent avant même que le standby ait eu une chance de prendre
# le relais. Cette garde, installée AVANT l'import du bootstrap/cogs, transforme uniquement
# cette fenêtre d'initialisation en attente courte. Une vraie erreur RuntimeError différente
# continue d'être propagée normalement.
_original_wait_until_ready = discord.Client.wait_until_ready


async def _ha_safe_wait_until_ready(self):
    while True:
        try:
            return await _original_wait_until_ready(self)
        except RuntimeError as exc:
            if "properly initialised" not in str(exc):
                raise
            await asyncio.sleep(0.25)


if not getattr(discord.Client.wait_until_ready, "_sentrix_ha_init_guard", False):
    _ha_safe_wait_until_ready._sentrix_ha_init_guard = True
    _ha_safe_wait_until_ready._sentrix_original = _original_wait_until_ready
    discord.Client.wait_until_ready = _ha_safe_wait_until_ready


from utils.failover import FailoverConfigurationError, LeadershipGrant, SentriXFailoverCoordinator

import railway_boot as boot
from web import dashboard as dashboard_web

logger = logging.getLogger("bot.ha-boot")
coordinator = SentriXFailoverCoordinator()

_original_bot_start = boot.bot_main.BotAllInOne.start


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _install_ha_healthcheck() -> None:
    """Expose clairement leader/standby tout en gardant le healthcheck non-HA historique."""
    current = dashboard_web.handle_health
    if getattr(current, "_sentrix_ha_health", False):
        return

    async def ha_health(request):
        bot = request.app["bot"]
        ready = bool(bot.is_ready() and not bot.is_closed())
        ha = coordinator.health()

        if not coordinator.enabled:
            ok = ready
        else:
            # Un standby doit rester vivant sur Railway. "blocked" est accepté car une
            # panne Redis transitoire peut se réparer sans redémarrer le conteneur.
            ok = ready or ha["state"] in {"starting", "standby", "blocked", "leader"}

        payload = {
            "ok": bool(ok),
            "discord_ready": ready,
            "latency_ms": round(bot.latency * 1000) if ready else None,
            "failover": {
                "enabled": ha["enabled"],
                "state": ha["state"],
                "role": ha["role"],
                "leader": ha["leader"],
                "ttl_seconds": ha["ttl_seconds"],
                "leader_for_seconds": ha["leader_for_seconds"],
                "error": ha["error"],
            },
        }
        return aiohttp_web.json_response(payload, status=200 if ok else 503)

    ha_health._sentrix_ha_health = True
    ha_health._sentrix_original = current
    dashboard_web.handle_health = ha_health
    logger.info("Healthcheck Railway HA installé.")


async def _restore_for_takeover(bot: Any, durable: Any) -> dict[str, Any]:
    """Ferme SQLite, restaure PostgreSQL puis reconnecte réellement la couche DB."""
    previous_force_restore = bool(getattr(durable, "force_restore", False))
    await bot.db.close()
    try:
        durable.force_restore = True
        result = await asyncio.wait_for(durable.restore_latest_if_needed(), timeout=60)
    finally:
        durable.force_restore = previous_force_restore

        # railway_boot.run() remplace volontairement l'attribut d'instance
        # `bot.db.connect` par un no-op après la première connexion afin que le démarrage
        # historique n'ouvre pas SQLite deux fois. Lors d'un takeover HA, nous venons au
        # contraire de FERMER la connexion pour restaurer le fichier depuis PostgreSQL :
        # rappeler `bot.db.connect()` ici invoquerait donc ce no-op et laisserait
        # aiosqlite fermé, ce qui provoquait en boucle `ValueError: no active connection`.
        # Appeler la méthode de la classe contourne uniquement ce monkey-patch d'instance
        # et rouvre la vraie connexion sur le fichier fraîchement restauré.
        real_connect = type(bot.db).connect.__get__(bot.db, type(bot.db))
        await real_connect()

    return result


def _guard_durable_snapshots(durable: Any) -> None:
    """Empêche une ancienne instance fenced d'écraser les snapshots du nouveau leader."""
    if getattr(durable, "_sentrix_ha_guarded", False):
        return

    original_snapshot = durable.snapshot

    async def guarded_snapshot(*, reason: str = "periodic", clean_shutdown: bool = False):
        if coordinator.enabled and not coordinator.is_leader:
            return {
                "stored": False,
                "reason": "not_failover_leader",
                "failover_state": coordinator.state,
            }
        return await original_snapshot(reason=reason, clean_shutdown=clean_shutdown)

    durable.snapshot = guarded_snapshot
    durable._sentrix_ha_guarded = True


async def _prepare_leader_storage(
    bot: Any,
    durable: Any,
    grant: LeadershipGrant,
) -> None:
    if not coordinator.enabled:
        return

    if durable is None or not durable.configured:
        raise FailoverConfigurationError(
            "Le failover exige PostgreSQL durable. Configure POSTGRES_URL/DATABASE_URL "
            "vers le service Postgres de SentriX."
        )
    if durable.pool is None and not await durable.connect():
        raise FailoverConfigurationError(
            f"PostgreSQL durable indisponible: {getattr(durable, 'error', 'erreur inconnue')}"
        )

    _guard_durable_snapshots(durable)

    takeover = coordinator.role == "standby" or not grant.acquired_immediately
    if takeover:
        result = await _restore_for_takeover(bot, durable)
        if not result.get("restored"):
            raise RuntimeError(
                "Takeover HA refusé: aucun snapshot PostgreSQL restaurable. "
                f"détail={result}"
            )
        logger.warning(
            "HA: takeover prêt après restauration snapshot=%s attente=%.1fs.",
            result.get("snapshot_id"),
            grant.waited_seconds,
        )
        return

    # Le principal possède déjà son volume SQLite historique. Avant d'autoriser un
    # secours, on pousse un snapshot de référence afin de ne jamais démarrer d'une copie vide.
    seed = await asyncio.wait_for(
        durable.snapshot(reason="ha_primary_seed", clean_shutdown=False),
        timeout=60,
    )
    if not seed.get("stored"):
        raise RuntimeError(f"Initialisation durable HA impossible: {seed}")
    logger.info("HA: snapshot primaire de référence stocké id=%s.", seed.get("snapshot_id"))


async def _periodic_snapshot_loop(bot: Any, durable: Any) -> None:
    interval = _env_int("SENTRIX_FAILOVER_SNAPSHOT_INTERVAL", 300, 60, 3600)
    try:
        while coordinator.is_leader and not bot.is_closed():
            await asyncio.sleep(interval)
            if not coordinator.is_leader or bot.is_closed():
                return
            result = await durable.snapshot(reason="ha_periodic", clean_shutdown=False)
            if result.get("stored"):
                logger.info("HA: snapshot périodique id=%s.", result.get("snapshot_id"))
            else:
                logger.warning("HA: snapshot périodique non stocké: %s", result)
    except asyncio.CancelledError:
        return
    except Exception:
        logger.warning("HA: boucle snapshot en erreur:\n%s", traceback.format_exc())


async def _ha_bot_start(self, token: str, *args, **kwargs):
    if not coordinator.enabled:
        return await _original_bot_start(self, token, *args, **kwargs)

    grant = await coordinator.wait_for_leadership()
    durable = getattr(self, "sentrix_durable_store", None)

    try:
        await _prepare_leader_storage(self, durable, grant)
    except Exception:
        # Le lease n'est pas utile si l'état persistant n'est pas sûr. On le rend avant
        # de faire échouer le déploiement pour qu'une autre instance saine puisse essayer.
        await coordinator.release()
        raise

    coordinator.start_watchdog(self)
    snapshot_task = asyncio.create_task(
        _periodic_snapshot_loop(self, durable),
        name="sentrix-ha-periodic-snapshot",
    )
    logger.warning(
        "HA: cette instance devient ACTIVE sur Discord (role=%s, attente=%.1fs).",
        coordinator.role,
        grant.waited_seconds,
    )
    try:
        return await _original_bot_start(self, token, *args, **kwargs)
    finally:
        snapshot_task.cancel()
        try:
            await snapshot_task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass


# Patch local au launcher HA uniquement. Le launcher railway_boot.py historique reste inchangé.
boot.bot_main.BotAllInOne.start = _ha_bot_start
boot._install_discord_readiness_healthcheck = _install_ha_healthcheck


async def run() -> None:
    try:
        await boot.run()
    finally:
        # railway_boot.run() a déjà tenté son snapshot d'arrêt à ce stade. Le lease est donc
        # libéré seulement APRES la persistance, évitant qu'un standby restaure trop tôt.
        await coordinator.close(release=True)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Arrêt de SentriX HA.")
