"""Correctif V3 ciblé sur les deux trous encore observables en production.

- pose le contexte de commande pendant TOUTE l'exécution d'une commande préfixée ;
  ainsi ``ctx.channel.send`` / ``channel.send`` sont aussi convertis en embeds ;
- réactive une seule fois toutes les routes de logs historiques valides afin de sortir
  d'une migration V2 marquée trop tôt, puis laisse les réglages futurs tranquilles.
"""
from __future__ import annotations

import asyncio
import logging
import time
import types
from typing import Any

import discord
from discord.ext import commands

from . import command_embed_invariant as invariant
from . import final_interaction_policy as policy
from . import production_embed_log_repair as v2
from . import runtime_fix_v1
from utils import log_service

logger = logging.getLogger("bot.production-embed-log-repair-v3")

_MIGRATION_KEY = "production_embed_log_repair_v3_force_routes"
_MIGRATION_TABLE = "sentrix_runtime_migrations_v3"
_INVOKE_MARKER = "_sentrix_prefix_command_context_v3"
_EMITTING_LOG_TYPES = tuple(
    name for name, meta in log_service.LOG_TYPES.items() if bool(meta.get("emits"))
)


def _state(bot: commands.Bot) -> dict[str, Any]:
    state = getattr(bot, "sentrix_embed_log_repair_v3_state", None)
    if not isinstance(state, dict):
        state = {
            "installed": False,
            "prefix_execution_context": False,
            "logs_cog_loaded": False,
            "log_listener_count": 0,
            "guilds_checked": 0,
            "guilds_force_recovered": 0,
            "configured_log_routes": 0,
            "enabled_log_routes": 0,
            "last_repair_at": None,
            "last_error": None,
        }
        bot.sentrix_embed_log_repair_v3_state = state
    return state


def _install_prefix_execution_context(bot: commands.Bot) -> None:
    """Garde la racine de commande active même si le callback utilise channel.send."""
    current = bot.invoke
    function = getattr(current, "__func__", current)
    if getattr(function, _INVOKE_MARKER, False):
        _state(bot)["prefix_execution_context"] = True
        return

    async def invoke_with_root(_bot: commands.Bot, ctx: commands.Context):
        root = policy._root_name(getattr(ctx, "command", None))
        token = policy._COMMAND_ROOT.set(root)
        try:
            return await current(ctx)
        finally:
            policy._COMMAND_ROOT.reset(token)

    setattr(invoke_with_root, _INVOKE_MARKER, True)
    invoke_with_root._sentrix_original = function
    bot.invoke = types.MethodType(invoke_with_root, bot)
    _state(bot)["prefix_execution_context"] = True


async def _ensure_migration_table(bot: commands.Bot) -> None:
    # Cette table est volontairement propre à V3. Un ancien module avait déjà créé
    # ``sentrix_runtime_migrations`` avec un schéma différent en production ; CREATE TABLE
    # IF NOT EXISTS ne migrait donc rien et chaque SELECT sur guild_id échouait au boot.
    await bot.db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_MIGRATION_TABLE} (
            guild_id INTEGER NOT NULL,
            migration_key TEXT NOT NULL,
            applied_at INTEGER NOT NULL,
            PRIMARY KEY (guild_id, migration_key)
        )
        """
    )


async def _migration_applied(bot: commands.Bot, guild_id: int) -> bool:
    row = await bot.db.fetchone(
        f"SELECT 1 AS ok FROM {_MIGRATION_TABLE} WHERE guild_id = ? AND migration_key = ?",
        (int(guild_id), _MIGRATION_KEY),
    )
    return bool(row)


async def _mark_migration(bot: commands.Bot, guild_id: int) -> None:
    await bot.db.execute(
        f"INSERT INTO {_MIGRATION_TABLE} (guild_id, migration_key, applied_at) "
        "VALUES (?, ?, ?) ON CONFLICT(guild_id, migration_key) DO NOTHING",
        (int(guild_id), _MIGRATION_KEY, int(time.time())),
    )


async def _ensure_logs_cog(bot: commands.Bot) -> tuple[bool, int]:
    cog = bot.get_cog("Logs")
    if cog is None:
        try:
            if "cogs.logs" in bot.extensions:
                await bot.reload_extension("cogs.logs")
            else:
                await bot.load_extension("cogs.logs")
        except Exception:
            logger.exception("Impossible de restaurer le Cog Logs en V3.")
        cog = bot.get_cog("Logs")

    listeners = 0
    if cog is not None:
        try:
            listeners = len(cog.get_listeners())
        except Exception:
            pass
    return cog is not None, listeners


async def _valid_routes(bot: commands.Bot, guild: discord.Guild) -> list[tuple[str, dict]]:
    # Répare d'abord les anciens channel_id / permissions à partir de guild_config.
    try:
        await runtime_fix_v1.repair_guild_logs(bot, guild, force_enable=False)
    except Exception:
        logger.exception("Réparation de routage préalable impossible guild=%s.", guild.id)

    routes: list[tuple[str, dict]] = []
    for log_type in _EMITTING_LOG_TYPES:
        try:
            setting = await log_service.get_log_setting(bot, guild.id, log_type)
        except Exception:
            logger.exception("Lecture route %s impossible guild=%s.", log_type, guild.id)
            continue
        channel_id = setting.get("channel_id")
        if not channel_id:
            continue
        ok, _reason = log_service.validate_channel(guild, int(channel_id))
        if ok:
            routes.append((log_type, setting))
    return routes


async def repair_guild_runtime(bot: commands.Bot, guild: discord.Guild) -> dict[str, int | bool]:
    """Force une fois toutes les routes historiques valides à enabled=1."""
    await _ensure_migration_table(bot)
    routes = await _valid_routes(bot, guild)
    configured = len(routes)
    applied = await _migration_applied(bot, guild.id)
    recovered = False

    if not applied and configured:
        enabled = 0
        for log_type, _setting in routes:
            try:
                await log_service.set_log_enabled(bot, guild.id, log_type, True)
                enabled += 1
            except Exception:
                logger.exception("Activation V3 impossible %s guild=%s.", log_type, guild.id)
        recovered = enabled > 0
        await _mark_migration(bot, guild.id)
        logger.warning(
            "Migration logs V3 appliquée guild=%s : %s/%s route(s) activée(s).",
            guild.id,
            enabled,
            configured,
        )
    else:
        enabled = sum(1 for _kind, setting in routes if bool(setting.get("enabled")))
        if not applied:
            await _mark_migration(bot, guild.id)

    return {"configured": configured, "enabled": enabled, "recovered": recovered}


class ProductionEmbedLogRepairV3(commands.Cog, name="ProductionEmbedLogRepairV3"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._ready_task: asyncio.Task | None = None

    async def _repair_all(self) -> None:
        state = _state(self.bot)
        state["last_error"] = None
        loaded, listeners = await _ensure_logs_cog(self.bot)
        state["logs_cog_loaded"] = loaded
        state["log_listener_count"] = listeners

        checked = recovered = configured = enabled = 0
        for guild in list(self.bot.guilds):
            try:
                result = await repair_guild_runtime(self.bot, guild)
                checked += 1
                recovered += int(bool(result["recovered"]))
                configured += int(result["configured"])
                enabled += int(result["enabled"])
            except Exception as exc:
                state["last_error"] = type(exc).__name__
                logger.exception("Réparation V3 impossible guild=%s.", guild.id)

        state.update(
            {
                "guilds_checked": checked,
                "guilds_force_recovered": recovered,
                "configured_log_routes": configured,
                "enabled_log_routes": enabled,
                "last_repair_at": int(time.time()),
            }
        )
        logger.info(
            "V3 runtime actif : context_prefix=%s Logs=%s listeners=%s guilds=%s routes=%s actives=%s récupérées=%s.",
            state.get("prefix_execution_context"),
            loaded,
            listeners,
            checked,
            configured,
            enabled,
            recovered,
        )

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._ready_task is not None and not self._ready_task.done():
            return
        self._ready_task = asyncio.create_task(self._repair_all())

    @commands.Cog.listener()
    async def on_guild_available(self, guild: discord.Guild) -> None:
        try:
            await repair_guild_runtime(self.bot, guild)
        except Exception:
            logger.exception("Réparation V3 on_guild_available impossible guild=%s.", guild.id)


def _install_health_patch(bot: commands.Bot) -> None:
    try:
        from web import production_health
    except Exception:
        return
    current = production_health._safe_slash_health
    if getattr(current, "_sentrix_embed_log_repair_v3", False):
        return

    def safe_health(runtime_bot: commands.Bot):
        payload = current(runtime_bot)
        if not isinstance(payload, dict):
            payload = {}
        payload["embed_log_runtime_v3"] = dict(_state(runtime_bot))
        return payload

    safe_health._sentrix_embed_log_repair_v3 = True
    safe_health._sentrix_original = current
    production_health._safe_slash_health = safe_health


async def setup(bot: commands.Bot) -> None:
    # Réapplique les protections V2 utiles, puis ferme le trou d'exécution préfixée.
    invariant.install(bot)
    v2._force_all_command_embeds()
    v2._install_direct_prefix_transport(bot)
    _install_prefix_execution_context(bot)
    runtime_fix_v1._install_log_producer_fix()

    loaded, listeners = await _ensure_logs_cog(bot)
    state = _state(bot)
    state.update(
        {
            "installed": True,
            "prefix_execution_context": True,
            "logs_cog_loaded": loaded,
            "log_listener_count": listeners,
        }
    )

    existing = bot.get_cog("ProductionEmbedLogRepairV3")
    if existing is not None:
        await bot.remove_cog("ProductionEmbedLogRepairV3")
    await bot.add_cog(ProductionEmbedLogRepairV3(bot))
    _install_health_patch(bot)

    logger.info("Correctif production V3 installé en dernière autorité runtime.")


__all__ = ["setup", "repair_guild_runtime", "_install_prefix_execution_context"]
