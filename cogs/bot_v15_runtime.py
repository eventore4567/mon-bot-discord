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
            "log_settings": {},
            "seen_prefix_messages": {},
            "log_cache_patched": False,
            "duplicate_guard_patched": False,
            "guild_listener_installed": False,
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


def _install_log_setting_cache(bot: commands.Bot) -> None:
    """Évite une lecture SQLite à chaque log tout en gardant les changements quasi immédiats."""
    from utils import log_service

    state = _state(bot)
    if state["log_cache_patched"]:
        return
    current_get = log_service.get_log_setting
    current_set_enabled = log_service.set_log_enabled
    current_set_channel = log_service.set_log_channel

    if getattr(current_get, "_sentrix_v15_cache", False):
        state["log_cache_patched"] = True
        return

    def cache_key(runtime_bot, guild_id: int, log_type: str):
        return (id(runtime_bot), int(guild_id), str(log_type))

    def cache_put(key, value: dict) -> dict:
        cache = state["log_settings"]
        if len(cache) >= MAX_CACHE_ITEMS:
            _prune_timed(cache, LOG_SETTING_TTL)
        clean = dict(value)
        cache[key] = (time.monotonic(), clean)
        return dict(clean)

    def cache_drop(runtime_bot, guild_id: int, log_type: str | None = None) -> None:
        cache = state["log_settings"]
        prefix = (id(runtime_bot), int(guild_id))
        if log_type is not None:
            cache.pop(prefix + (str(log_type),), None)
            return
        for key in [key for key in cache if key[:2] == prefix]:
            cache.pop(key, None)

    async def get_log_setting_v15(runtime_bot, guild_id: int, log_type: str) -> dict:
        key = cache_key(runtime_bot, guild_id, log_type)
        cached = state["log_settings"].get(key)
        if cached is not None and time.monotonic() - float(cached[0]) <= LOG_SETTING_TTL:
            return dict(cached[1])
        state["log_settings"].pop(key, None)
        value = await current_get(runtime_bot, int(guild_id), str(log_type))
        return cache_put(key, value)

    async def set_log_enabled_v15(runtime_bot, guild_id: int, log_type: str, enabled: bool) -> dict:
        # On invalide avant ET après : l'implémentation historique appelle get_log_setting
        # plusieurs fois pendant la modification.
        cache_drop(runtime_bot, guild_id, log_type)
        result = await current_set_enabled(runtime_bot, int(guild_id), str(log_type), bool(enabled))
        cache_drop(runtime_bot, guild_id, log_type)
        return cache_put(cache_key(runtime_bot, guild_id, log_type), result)

    async def set_log_channel_v15(runtime_bot, guild_id: int, log_type: str, channel_id: int | None) -> dict:
        cache_drop(runtime_bot, guild_id, log_type)
        # Réimplémentation minuscule pour éviter que le get interne de l'ancienne fonction
        # ne relise une valeur mise en cache juste avant l'UPDATE.
        await get_log_setting_v15(runtime_bot, int(guild_id), str(log_type))
        cursor = await runtime_bot.db.execute(
            "UPDATE log_settings SET channel_id = ?, updated_at = ? WHERE guild_id = ? AND log_type = ?",
            (channel_id, log_service._now(), int(guild_id), str(log_type)),
        )
        # SXTRACE 7 : cette fonction n'ecrit QUE dans log_settings. Si rowcount vaut 0,
        # aucune ligne n'a ete touchee, aucun trigger n'a pu se declencher, et log_config
        # — la seule table lue par send_log — reste inchangee. Le retour force pourtant
        # channel_id plus bas, ce qui affiche "ACTIF" dans le panneau.
        rowcount = getattr(cursor, "rowcount", None)
        try:
            written = await runtime_bot.db.fetchone(
                "SELECT channel_id, enabled, updated_at FROM log_config "
                "WHERE guild_id = ? AND category = ?",
                (int(guild_id), str(log_type)),
            )
        except Exception as exc:  # pragma: no cover - diagnostic uniquement
            written = f"<erreur {type(exc).__name__}>"
        logger.warning(
            "SXTRACE 7 SETUP_WRITE guild=%s log_type=%s asked_channel=%s "
            "log_settings_rowcount=%s log_config_readback=%s",
            guild_id, log_type, channel_id, rowcount,
            dict(written) if hasattr(written, "keys") else written,
        )
        cache_drop(runtime_bot, guild_id, log_type)
        value = await current_get(runtime_bot, int(guild_id), str(log_type))
        value["channel_id"] = channel_id
        return cache_put(cache_key(runtime_bot, guild_id, log_type), value)

    get_log_setting_v15._sentrix_v15_cache = True
    get_log_setting_v15._sentrix_original = current_get
    set_log_enabled_v15._sentrix_v15_cache = True
    set_log_enabled_v15._sentrix_original = current_set_enabled
    set_log_channel_v15._sentrix_v15_cache = True
    set_log_channel_v15._sentrix_original = current_set_channel

    log_service.get_log_setting = get_log_setting_v15
    log_service.set_log_enabled = set_log_enabled_v15
    log_service.set_log_channel = set_log_channel_v15
    log_service.invalidate_log_cache = cache_drop
    state["log_cache_patched"] = True
    logger.info("V15 : cache court des réglages de logs actif (%ss).", LOG_SETTING_TTL)


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


def _install_guild_cleanup(bot: commands.Bot) -> None:
    state = _state(bot)
    if state["guild_listener_installed"]:
        return

    async def cleanup_guild(guild) -> None:
        gid = int(guild.id)
        cache = state["log_settings"]
        for key in [key for key in cache if len(key) >= 3 and int(key[1]) == gid]:
            cache.pop(key, None)

    bot.add_listener(cleanup_guild, "on_guild_remove")
    state["guild_listener_installed"] = True


def install(bot: commands.Bot, extension_name: str = "") -> None:
    """Réappliqué après les extensions ; chaque sous-patch reste idempotent."""
    _install_log_setting_cache(bot)
    _install_duplicate_command_guard(bot)
    _install_batched_production_metrics(bot)
    _install_guild_cleanup(bot)
    bot._sentrix_v15_active = True


__all__ = ["install"]
