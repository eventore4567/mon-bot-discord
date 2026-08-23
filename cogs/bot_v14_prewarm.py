"""V14 cache prewarm for SentriX.

Loads the small, frequently-read configuration tables once after Discord becomes ready so
first-message/first-command traffic does not cause a burst of individual SQLite reads.
No dashboard code and no public command are added.
"""
from __future__ import annotations

import asyncio
import logging

import config
import discord
from discord.ext import commands

logger = logging.getLogger("bot.v14-prewarm")


def _row_guild_id(row) -> int | None:
    try:
        return int(row["guild_id"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


async def _prewarm(bot: commands.Bot) -> None:
    if bot.is_closed():
        return
    db = getattr(bot, "db", None)
    conn = getattr(db, "_conn", None)
    if db is None or conn is None:
        return

    # If short write contention occurs, wait instead of immediately surfacing a transient
    # "database is locked" error to a real Discord command.
    try:
        await conn.execute("PRAGMA busy_timeout=5000")
        await conn.execute("PRAGMA optimize")
    except Exception:
        logger.debug("V14 SQLite tuning unavailable.", exc_info=True)

    guild_ids = {int(g.id) for g in bot.guilds}
    if not guild_ids:
        return

    warmed_config = 0
    warmed_automod = 0

    # guild_config is already cached by Database. Populate that cache in one SELECT instead
    # of waiting for every server to issue its own first read.
    try:
        rows = await db.fetchall("SELECT * FROM guild_config")
        cache = getattr(db, "_guild_config_cache", None)
        prefix_cache = getattr(bot, "prefix_cache", None)
        if isinstance(cache, dict):
            for row in rows:
                gid = _row_guild_id(row)
                if gid is None or gid not in guild_ids:
                    continue
                cache[gid] = row
                warmed_config += 1
                if isinstance(prefix_cache, dict):
                    try:
                        prefix_cache[gid] = str(row["prefix"] or config.DEFAULT_PREFIX)
                    except Exception:
                        prefix_cache[gid] = config.DEFAULT_PREFIX
    except Exception:
        logger.warning("V14 : préchargement guild_config impossible, cache paresseux conservé.", exc_info=True)

    # AutoMod already owns an in-memory cache. Fill it with one table read once all cogs are
    # loaded. Runtime commands still invalidate their own guild entry when a setting changes.
    automod = bot.get_cog("Automod")
    automod_cache = getattr(automod, "automod_cache", None) if automod else None
    if isinstance(automod_cache, dict):
        try:
            rows = await db.fetchall("SELECT * FROM automod_settings")
            for row in rows:
                gid = _row_guild_id(row)
                if gid is None or gid not in guild_ids:
                    continue
                automod_cache.setdefault(gid, dict(row))
                warmed_automod += 1
        except Exception:
            logger.warning("V14 : préchargement AutoMod impossible, cache paresseux conservé.", exc_info=True)

    logger.info(
        "V14 prewarm : %s configuration(s) et %s profil(s) AutoMod prêts en mémoire.",
        warmed_config,
        warmed_automod,
    )


async def _warm_new_guild(bot: commands.Bot, guild: discord.Guild) -> None:
    try:
        conf = await bot.db.get_guild_config(guild.id)
        prefix_cache = getattr(bot, "prefix_cache", None)
        if isinstance(prefix_cache, dict):
            prefix_cache[guild.id] = str(conf["prefix"] or config.DEFAULT_PREFIX) if conf else config.DEFAULT_PREFIX
        automod = bot.get_cog("Automod")
        if automod is not None and hasattr(automod, "get_automod_cached"):
            await automod.get_automod_cached(guild.id)
    except Exception:
        logger.debug("V14 : préchauffage du nouveau serveur %s impossible.", guild.id, exc_info=True)


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_v14_prewarm_installed", False):
        return
    bot._sentrix_v14_prewarm_installed = True

    async def ready_listener() -> None:
        # Yield once so all on_ready bookkeeping can settle; the bulk V14 bootstrap runs
        # before the normal BotAllInOne.on_ready path.
        await asyncio.sleep(0)
        await _prewarm(bot)

    async def guild_join_listener(guild: discord.Guild) -> None:
        await _warm_new_guild(bot, guild)

    async def guild_remove_listener(guild: discord.Guild) -> None:
        cache = getattr(bot.db, "_guild_config_cache", None)
        if isinstance(cache, dict):
            cache.pop(guild.id, None)
        prefix_cache = getattr(bot, "prefix_cache", None)
        if isinstance(prefix_cache, dict):
            prefix_cache.pop(guild.id, None)
        automod = bot.get_cog("Automod")
        automod_cache = getattr(automod, "automod_cache", None) if automod else None
        if isinstance(automod_cache, dict):
            automod_cache.pop(guild.id, None)

    bot.add_listener(ready_listener, "on_ready")
    bot.add_listener(guild_join_listener, "on_guild_join")
    bot.add_listener(guild_remove_listener, "on_guild_remove")
    logger.info("V14 cache prewarm enregistré.")


__all__ = ["install"]
