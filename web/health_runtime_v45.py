"""Santé production SentriX V45.

Améliore /health sans casser les healthchecks existants et ajoute /ready pour les
contrôles stricts. Aucune donnée sensible n'est exposée.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

from aiohttp import web

logger = logging.getLogger("bot.dashboard.health-runtime-v45")
_INSTALLED = False
_DB_TIMEOUT_SECONDS = 2.5


def _release_id() -> str:
    for key in ("RAILWAY_GIT_COMMIT_SHA", "GIT_COMMIT_SHA", "SOURCE_VERSION", "COMMIT_SHA"):
        value = str(os.getenv(key, "") or "").strip()
        if value:
            return value[:12]
    return "inconnu"


def _truthy_env(name: str) -> bool:
    return (os.getenv(name, "") or "").strip().lower() in {"1", "true", "yes", "on"}


def _ha_runtime_state(bot) -> tuple[bool, bool, str, str]:
    """Retourne (enabled, leader, role, state) depuis le coordinateur HA vivant.

    Le launcher attache son coordinateur au bot avant d'attendre le lease Redis. On garde
    un fallback environnemental uniquement pour la toute petite fenêtre avant cet attach.
    """
    coordinator = getattr(bot, "_sentrix_ha_coordinator", None)
    if coordinator is not None:
        return (
            bool(getattr(coordinator, "enabled", False)),
            bool(getattr(coordinator, "is_leader", False)),
            str(getattr(coordinator, "role", "inconnu") or "inconnu"),
            str(getattr(coordinator, "state", "starting") or "starting"),
        )

    enabled = _truthy_env("SENTRIX_FAILOVER_ENABLED")
    role = (os.getenv("SENTRIX_FAILOVER_ROLE", "") or "").strip().lower() or "inconnu"
    return enabled, False, role, "starting"


def _ha_passive_instance(bot) -> bool:
    enabled, leader, _role, state = _ha_runtime_state(bot)
    return enabled and not leader and state in {"starting", "standby"}


def _count_members(bot) -> int:
    return sum(max(0, int(getattr(guild, "member_count", 0) or 0)) for guild in getattr(bot, "guilds", []) or [])


async def _database_probe(bot) -> tuple[bool, float | None]:
    started = time.perf_counter()
    try:
        row = await asyncio.wait_for(bot.db.fetchone("SELECT 1 AS ok"), timeout=_DB_TIMEOUT_SECONDS)
        ok = bool(row and int(row["ok"]) == 1)
    except Exception:
        return False, None
    return ok, round((time.perf_counter() - started) * 1000, 2)


def _extension_state(bot) -> tuple[int, int, bool]:
    loaded = len(getattr(bot, "extensions", {}) or {})
    expected = int(getattr(bot, "expected_extension_count", loaded) or loaded)
    return loaded, expected, loaded >= expected


def _command_policy_state(bot) -> tuple[bool, int, int]:
    audit = getattr(bot, "_sentrix_command_audit", None)
    if not isinstance(audit, dict):
        return True, 0, 0
    unknown = len(audit.get("unknown_policy") or [])
    dangerous = len(audit.get("dangerous_public") or [])
    # Les commandes inconnues sont fail-closed dans V41 ; elles dégradent le diagnostic
    # mais ne rendent pas le bot dangereux. Une commande destructive publique, oui.
    return dangerous == 0, unknown, dangerous


def _backup_state(bot) -> bool | None:
    ops = getattr(bot, "_sentrix_production_ops", None)
    if not isinstance(ops, dict):
        return None
    value = ops.get("last_backup_ok")
    return bool(value) if value is not None else None


async def _snapshot(bot, dashboard) -> dict:
    database_ok, database_latency_ms = await _database_probe(bot)
    loaded_extensions, expected_extensions, extensions_ok = _extension_state(bot)
    command_policy_ok, unknown_commands, dangerous_public_commands = _command_policy_state(bot)
    discord_ready = bool(bot.is_ready())

    latency_ms = None
    if discord_ready:
        try:
            latency_ms = round(float(bot.latency) * 1000)
        except (TypeError, ValueError):
            latency_ms = None

    healthy = bool(discord_ready and database_ok and extensions_ok and command_policy_ok)
    if healthy:
        status = "operational"
    elif not database_ok:
        status = "database_unavailable"
    elif not extensions_ok:
        status = "extensions_degraded"
    elif not command_policy_ok:
        status = "security_degraded"
    elif not discord_ready:
        status = "discord_not_ready"
    else:
        status = "degraded"

    start_time = float(getattr(dashboard, "START_TIME", time.time()) or time.time())
    return {
        "ok": healthy,
        "status": status,
        "discord_ready": discord_ready,
        "database_ok": database_ok,
        "database_latency_ms": database_latency_ms,
        "extensions_ok": extensions_ok,
        "extensions_loaded": loaded_extensions,
        "extensions_expected": expected_extensions,
        "command_policy_ok": command_policy_ok,
        "unknown_command_policy_count": unknown_commands,
        "dangerous_public_command_count": dangerous_public_commands,
        "latency_ms": latency_ms,
        "guild_count": len(getattr(bot, "guilds", []) or []),
        "member_count": _count_members(bot),
        "uptime_seconds": max(0, int(time.time() - start_time)),
        "backup_ok": _backup_state(bot),
        "release": _release_id(),
    }


def _headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store, max-age=0",
        "Pragma": "no-cache",
        "X-Robots-Tag": "noindex, nofollow",
    }


async def enhanced_health(request: web.Request) -> web.Response:
    """Liveness détaillée : reste HTTP 200 pour éviter les boucles de restart Railway."""
    data = await _snapshot(request.app["bot"], request.app["dashboard_module"])
    return web.json_response(data, status=200, headers=_headers())


async def strict_readiness(request: web.Request) -> web.Response:
    """Readiness stricte : 503 tant que les composants critiques ne sont pas prêts."""
    data = await _snapshot(request.app["bot"], request.app["dashboard_module"])
    return web.json_response(data, status=200 if data["ok"] else 503, headers=_headers())


async def _alert_degraded_startup(bot, data: dict) -> None:
    """Réutilise le canal/DM ops existant sans dupliquer la logique d'alerte ni exposer de secret."""
    try:
        from cogs import production_ops

        sender = getattr(production_ops, "_send_ops_alert", None)
        if sender is None:
            return
        detail = (
            "Démarrage dégradé détecté : "
            f"status={data['status']}, Discord={data['discord_ready']}, DB={data['database_ok']}, "
            f"extensions={data['extensions_loaded']}/{data['extensions_expected']}, "
            f"policy={data['command_policy_ok']}."
        )
        await sender(bot, "startup-health-v45", detail)
    except Exception:
        logger.exception("Impossible d'envoyer l'alerte de démarrage V45.")


async def _boot_audit(bot, dashboard) -> None:
    try:
        await asyncio.wait_for(bot.wait_until_ready(), timeout=90)
    except asyncio.TimeoutError:
        enabled, leader, role, state = _ha_runtime_state(bot)

        # Une instance HA peut être saine tout en restant volontairement déconnectée de
        # Discord lorsqu'une autre instance détient le lease Redis. Cela vaut aussi pour
        # un primary pendant un rolling deploy, pas seulement pour le rôle standby.
        if _ha_passive_instance(bot):
            logger.info(
                "Audit démarrage V45 : instance HA passive en attente du lease "
                "(role=%s, state=%s).",
                role,
                state,
            )
            return

        # Redis indisponible est un incident à voir, mais le processus HA est conçu pour
        # rester vivant et retenter plutôt que de provoquer une boucle de redémarrage.
        if enabled and not leader and state == "blocked":
            logger.warning(
                "Audit démarrage V45 : instance HA bloquée en attente de Redis "
                "(role=%s).",
                role,
            )
            return

        # Si cette instance détient déjà le lease mais n'est toujours pas prête après
        # 90 secondes, c'est une vraie anomalie Discord et on conserve le niveau ERROR.
        logger.error("Audit démarrage V45 : Discord n'est pas devenu prêt en 90 secondes.")
        return
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Audit démarrage V45 impossible.")
        return

    data = await _snapshot(bot, dashboard)
    if data["ok"]:
        logger.info(
            "Audit démarrage V45 OK : Discord, DB et extensions prêts (%s/%s), DB %.2f ms.",
            data["extensions_loaded"],
            data["extensions_expected"],
            float(data["database_latency_ms"] or 0),
        )
    else:
        logger.error(
            "Audit démarrage V45 dégradé : status=%s discord=%s db=%s extensions=%s policy=%s.",
            data["status"],
            data["discord_ready"],
            data["database_ok"],
            data["extensions_ok"],
            data["command_policy_ok"],
        )
        await _alert_degraded_startup(bot, data)


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # dashboard.build_app résout handle_health au moment où l'application est construite.
    # Le remplacer ici améliore donc /health sans ajouter une route en doublon.
    dashboard.handle_health = enhanced_health
    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        app.router.add_get("/ready", strict_readiness)

        async def start_boot_audit(_app):
            _app["sentrix_health_boot_task"] = asyncio.create_task(
                _boot_audit(bot, dashboard),
                name="sentrix-health-boot-audit",
            )

        async def stop_boot_audit(_app):
            task = _app.get("sentrix_health_boot_task")
            if task is None or task.done():
                return
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        app.on_startup.append(start_boot_audit)
        app.on_cleanup.append(stop_boot_audit)
        return app

    dashboard.build_app = build_app
