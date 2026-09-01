"""SentriX V15 — runtime bot-only, sans dashboard.

Objectifs :
- éviter toute double exécution accidentelle d'une même commande préfixée ;
- mettre en cache quelques secondes la configuration des logs, très souvent lue ;
- invalider immédiatement ce cache lorsqu'une commande du bot modifie les logs ;
- écrire les métriques de commandes ProductionPhase en une seule transaction SQLite ;
- nettoyer les petits états mémoire quand le bot quitte un serveur.

Aucune commande publique n'est ajoutée et aucune permission n'est affaiblie.
"""
from __future__ import annotations

import logging
import time
from types import MethodType
from typing import Any

from discord.ext import commands

logger = logging.getLogger("bot.v15-runtime")

LOG_SETTING_TTL = 5.0
DUPLICATE_COMMAND_TTL = 5.0
MAX_CACHE_ITEMS = 12_000


def _state(bot: commands.Bot) -> dict[str, Any]:
    state = getattr(bot, "_sentrix_v15_state", None)
    if not isinstance(state, dict):
        state = {
            "seen_prefix_messages": {},
            "duplicate_guard_patched": False,
            "metrics_patch_target": None,
        }
        bot._sentrix_v15_state = state
    return state


def _prune_timed(cache: dict, ttl: float) -> None:
    if not cache:
        return
    mono = time.monotonic()
    if len(cache) < MAX_CACHE_ITEMS:
        # Nettoyage opportuniste léger uniquement quand il y a déjà des entrées anciennes.
        stale = [key for key, item in cache.items() if mono - float(item[0]) > ttl * 3]
    else:
        stale = [key for key, item in cache.items() if mono - float(item[0]) > ttl]
    for key in stale:
        cache.pop(key, None)
    if len(cache) > MAX_CACHE_ITEMS:
        for key in list(cache.keys())[: len(cache) - MAX_CACHE_ITEMS // 2]:
            cache.pop(key, None)


# _install_log_setting_cache SUPPRIMÉ.
#
# Il remplaçait log_service.set_log_channel par une réimplémentation qui écrivait
# UNIQUEMENT dans log_settings — jamais dans log_config, la seule table lue par le
# transport — puis forçait channel_id dans la valeur retournée et la mettait en cache
# sans vérifier qu'une ligne avait été touchée. Le panneau affichait donc "ACTIF" pour
# une route qui n'existait pas. log_service.set_log_config est désormais l'unique point
# d'écriture et relit systématiquement la base après écriture.


def _install_duplicate_command_guard(bot: commands.Bot) -> None:
    """Une même message-id Discord ne doit jamais déclencher deux fois une commande."""
    state = _state(bot)
    if state["duplicate_guard_patched"]:
        return
    current = bot.invoke
    function = getattr(current, "__func__", current)
    if getattr(function, "_sentrix_v15_duplicate_guard", False):
        state["duplicate_guard_patched"] = True
        return

    async def invoke_v15(_bot, ctx: commands.Context):
        command = getattr(ctx, "command", None)
        message = getattr(ctx, "message", None)
        message_id = int(getattr(message, "id", 0) or 0)
        if command is not None and message_id:
            seen = state["seen_prefix_messages"]
            mono = time.monotonic()
            previous = seen.get(message_id)
            if previous is not None and mono - float(previous) <= DUPLICATE_COMMAND_TTL:
                logger.warning(
                    "V15 : double exécution supprimée pour +%s (message=%s, user=%s, guild=%s).",
                    getattr(command, "qualified_name", "commande"),
                    message_id,
                    getattr(getattr(ctx, "author", None), "id", None),
                    getattr(getattr(ctx, "guild", None), "id", None),
                )
                return None
            seen[message_id] = mono
            if len(seen) >= MAX_CACHE_ITEMS:
                cutoff = mono - DUPLICATE_COMMAND_TTL * 3
                for key, stamp in list(seen.items()):
                    if float(stamp) < cutoff:
                        seen.pop(key, None)
        return await current(ctx)

    invoke_v15._sentrix_v15_duplicate_guard = True
    invoke_v15._sentrix_original = function
    bot.invoke = MethodType(invoke_v15, bot)
    state["duplicate_guard_patched"] = True
    logger.info("V15 : garde anti-double exécution des commandes préfixées actif.")


def _install_batched_production_metrics(bot: commands.Bot) -> None:
    """Remplace N commits/minute par une seule transaction pour les métriques runtime."""
    runtime = bot.get_cog("ProductionPhaseRuntime")
    if runtime is None:
        return
    state = _state(bot)
    target_id = id(runtime)
    if state.get("metrics_patch_target") == target_id:
        return

    current = runtime._flush_command_metrics
    function = getattr(current, "__func__", current)
    if getattr(function, "_sentrix_v15_batch_metrics", False):
        state["metrics_patch_target"] = target_id
        return

    async def flush_metrics_v15(_runtime):
        from database.db import now

        if not _runtime._command_buffer:
            return
        conn = getattr(getattr(_runtime.bot, "db", None), "_conn", None)
        if conn is None:
            return await current()

        snapshot = dict(_runtime._command_buffer)
        _runtime._command_buffer.clear()
        hour_bucket = int(now() // 3600 * 3600)
        rows = []
        for command_name, values in snapshot.items():
            calls, errors, total_ms, max_ms = values
            rows.append(
                (hour_bucket, str(command_name)[:120], int(calls), int(errors), float(total_ms), float(max_ms))
            )

        try:
            if rows:
                await conn.executemany(
                    "INSERT INTO production_command_metrics "
                    "(hour_bucket,command_name,calls,errors,total_ms,max_ms) VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(hour_bucket,command_name) DO UPDATE SET "
                    "calls=calls+excluded.calls, errors=errors+excluded.errors, "
                    "total_ms=total_ms+excluded.total_ms, max_ms=MAX(max_ms,excluded.max_ms)",
                    rows,
                )
            await conn.execute(
                "DELETE FROM production_command_metrics WHERE hour_bucket < ?",
                (int(now() - 7 * 86400),),
            )
            await conn.commit()
        except Exception:
            # Les métriques ne doivent jamais faire perdre les compteurs en mémoire.
            for command_name, values in snapshot.items():
                row = _runtime._command_buffer[command_name]
                for index in range(3):
                    row[index] += values[index]
                row[3] = max(row[3], values[3])
            logger.warning("V15 : flush groupé des métriques indisponible, repli au prochain cycle.", exc_info=True)

    flush_metrics_v15._sentrix_v15_batch_metrics = True
    flush_metrics_v15._sentrix_original = function
    runtime._flush_command_metrics = MethodType(flush_metrics_v15, runtime)
    state["metrics_patch_target"] = target_id
    logger.info("V15 : métriques commandes écrites en transaction groupée.")


# _install_guild_cleanup SUPPRIMÉ : il ne purgeait que le cache des réglages de logs.


def install(bot: commands.Bot, extension_name: str = "") -> None:
    """Réappliqué après les extensions ; chaque sous-patch reste idempotent."""
    _install_duplicate_command_guard(bot)
    _install_batched_production_metrics(bot)
    bot._sentrix_v15_active = True


__all__ = ["install"]
