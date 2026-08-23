"""SentriX V14 — fast-path runtime for the Discord bot itself.

This module deliberately does not touch the web dashboard and does not add public
commands.  It optimises paths that run for virtually every Discord command/event while
keeping the existing permission, moderation and persistence semantics intact:

- one-process guild bootstrap cache (two INSERT OR IGNORE + one commit only when needed);
- single-transaction bulk guild bootstrap before the normal on_ready work;
- short, bounded caches for creator/manager/category/alias lookups;
- automatic cache invalidation on the corresponding write methods;
- batched command_logs writes instead of one SQLite commit per completed command;
- delayed typing indicator for prefix commands that genuinely take a little time;
- bounded runtime state and cleanup on guild removal / database reconnect.

The patch is idempotent and fail-open for performance helpers: if an optimisation cannot
be installed, the original database/bot method remains the source of truth.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from types import MethodType
from typing import Any

import discord
from discord.ext import commands

logger = logging.getLogger("bot.v14-core")

CREATOR_CACHE_TTL = 60.0
MANAGER_CACHE_TTL = 20.0
MANAGER_CATEGORY_CACHE_TTL = 20.0
ALIAS_CACHE_TTL = 30.0
CACHE_MAX_ITEMS = 12_000

COMMAND_LOG_FLUSH_SECONDS = 2.0
COMMAND_LOG_BATCH_SIZE = 120
COMMAND_LOG_MAX_QUEUE = 6_000

TYPING_DELAY_SECONDS = 0.70
MAINTENANCE_SECONDS = 60.0

_MISSING = object()


def _session_started(bot: commands.Bot) -> bool:
    return bool(getattr(getattr(bot, "http", None), "token", None))


def _state(bot: commands.Bot) -> dict[str, Any]:
    state = getattr(bot, "_sentrix_v14_state", None)
    if state is None:
        state = {
            "installed": False,
            "db_patched": False,
            "ready_patched": False,
            "logging_patched": False,
            "listeners_installed": False,
            "conn_marker": None,
            "ensured_guilds": set(),
            "ensure_lock": asyncio.Lock(),
            "creator_cache": {},
            "manager_cache": {},
            "manager_category_cache": {},
            "alias_cache": {},
            "command_log_queue": deque(),
            "command_log_event": asyncio.Event(),
            "command_log_task": None,
            "typing_tasks": {},
            "maintenance_task": None,
            "dropped_command_logs": 0,
            "last_log_error": 0.0,
        }
        bot._sentrix_v14_state = state
    return state


def _sync_connection_epoch(bot: commands.Bot) -> None:
    """Invalidate hot caches whenever Database.connect() replaced the SQLite connection."""
    state = _state(bot)
    marker = id(getattr(getattr(bot, "db", None), "_conn", None))
    if state.get("conn_marker") == marker:
        return
    state["conn_marker"] = marker
    state["ensured_guilds"].clear()
    state["creator_cache"].clear()
    state["manager_cache"].clear()
    state["manager_category_cache"].clear()
    state["alias_cache"].clear()


def _cache_get(cache: dict, key, ttl: float):
    item = cache.get(key)
    if item is None:
        return _MISSING
    stamp, value = item
    if time.monotonic() - float(stamp) > ttl:
        cache.pop(key, None)
        return _MISSING
    return value


def _prune_cache(cache: dict, ttl: float, *, force_limit: bool = True) -> None:
    if not cache:
        return
    mono = time.monotonic()
    stale = [key for key, (stamp, _value) in cache.items() if mono - float(stamp) > ttl * 2.0]
    for key in stale:
        cache.pop(key, None)
    if not force_limit or len(cache) <= CACHE_MAX_ITEMS:
        return
    # dict preserves insertion order; drop the oldest quarter without sorting thousands
    # of entries on the event loop.
    remove_count = max(1, len(cache) - int(CACHE_MAX_ITEMS * 0.75))
    for key in list(cache.keys())[:remove_count]:
        cache.pop(key, None)


def _cache_put(cache: dict, key, value, ttl: float) -> None:
    if len(cache) >= CACHE_MAX_ITEMS:
        _prune_cache(cache, ttl)
    cache[key] = (time.monotonic(), value)


def _patch_database_hot_paths(bot: commands.Bot) -> None:
    state = _state(bot)
    db = getattr(bot, "db", None)
    if db is None or state.get("db_patched"):
        return

    _sync_connection_epoch(bot)

    # ------------------------------- ensure_guild: the hottest write path
    original_ensure = db.ensure_guild

    async def ensure_guild_v14(_db, guild_id: int):
        _sync_connection_epoch(bot)
        gid = int(guild_id)
        state = _state(bot)
        if gid in state["ensured_guilds"]:
            return None
        lock: asyncio.Lock = state["ensure_lock"]
        async with lock:
            _sync_connection_epoch(bot)
            if gid in state["ensured_guilds"]:
                return None
            conn = getattr(_db, "_conn", None)
            if conn is None:
                result = await original_ensure(gid)
            else:
                # Same semantics as Database.ensure_guild(), but one transaction/commit
                # instead of two independent commits.
                await conn.execute(
                    "INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)",
                    (gid,),
                )
                await conn.execute(
                    "INSERT OR IGNORE INTO automod_settings (guild_id) VALUES (?)",
                    (gid,),
                )
                await conn.commit()
                result = None
            state["ensured_guilds"].add(gid)
            return result

    ensure_guild_v14._sentrix_v14 = True
    ensure_guild_v14._sentrix_original = original_ensure
    db.ensure_guild = MethodType(ensure_guild_v14, db)

    # invalidate_guild_config is also used after destructive/reset operations.  Forgetting
    # the bootstrap marker here guarantees that a deleted row can be recreated immediately.
    original_invalidate = db.invalidate_guild_config

    def invalidate_guild_config_v14(_db, guild_id: int):
        result = original_invalidate(int(guild_id))
        state["ensured_guilds"].discard(int(guild_id))
        return result

    invalidate_guild_config_v14._sentrix_v14 = True
    db.invalidate_guild_config = MethodType(invalidate_guild_config_v14, db)

    # ------------------------------- creator check: currently hit by every normal command
    original_is_creator = db.is_bot_creator

    async def is_bot_creator_v14(_db, user_id: int) -> bool:
        _sync_connection_epoch(bot)
        uid = int(user_id)
        cache = state["creator_cache"]
        cached = _cache_get(cache, uid, CREATOR_CACHE_TTL)
        if cached is not _MISSING:
            return bool(cached)
        value = bool(await original_is_creator(uid))
        _cache_put(cache, uid, value, CREATOR_CACHE_TTL)
        return value

    is_bot_creator_v14._sentrix_v14 = True
    is_bot_creator_v14._sentrix_original = original_is_creator
    db.is_bot_creator = MethodType(is_bot_creator_v14, db)

    # ------------------------------- bot manager permission fast-paths
    original_is_manager = db.is_bot_manager
    original_add_manager = db.add_bot_manager
    original_remove_manager = db.remove_bot_manager
    original_get_categories = db.get_manager_categories
    original_set_categories = db.set_manager_categories

    async def is_bot_manager_v14(_db, guild_id: int, user_id: int) -> bool:
        _sync_connection_epoch(bot)
        key = (int(guild_id), int(user_id))
        cached = _cache_get(state["manager_cache"], key, MANAGER_CACHE_TTL)
        if cached is not _MISSING:
            return bool(cached)
        value = bool(await original_is_manager(*key))
        _cache_put(state["manager_cache"], key, value, MANAGER_CACHE_TTL)
        return value

    async def add_bot_manager_v14(_db, guild_id: int, user_id: int, added_by: int):
        result = await original_add_manager(int(guild_id), int(user_id), int(added_by))
        key = (int(guild_id), int(user_id))
        state["manager_cache"].pop(key, None)
        state["manager_category_cache"].pop(key, None)
        return result

    async def remove_bot_manager_v14(_db, guild_id: int, user_id: int):
        result = await original_remove_manager(int(guild_id), int(user_id))
        key = (int(guild_id), int(user_id))
        state["manager_cache"].pop(key, None)
        state["manager_category_cache"].pop(key, None)
        return result

    async def get_manager_categories_v14(_db, guild_id: int, user_id: int) -> list[str]:
        _sync_connection_epoch(bot)
        key = (int(guild_id), int(user_id))
        cached = _cache_get(state["manager_category_cache"], key, MANAGER_CATEGORY_CACHE_TTL)
        if cached is not _MISSING:
            return list(cached)
        value = list(await original_get_categories(*key))
        _cache_put(state["manager_category_cache"], key, tuple(value), MANAGER_CATEGORY_CACHE_TTL)
        return value

    async def set_manager_categories_v14(
        _db,
        guild_id: int,
        user_id: int,
        categories: list[str],
        granted_by: int,
    ):
        result = await original_set_categories(
            int(guild_id), int(user_id), list(categories), int(granted_by)
        )
        key = (int(guild_id), int(user_id))
        state["manager_category_cache"].pop(key, None)
        state["manager_cache"].pop(key, None)
        return result

    db.is_bot_manager = MethodType(is_bot_manager_v14, db)
    db.add_bot_manager = MethodType(add_bot_manager_v14, db)
    db.remove_bot_manager = MethodType(remove_bot_manager_v14, db)
    db.get_manager_categories = MethodType(get_manager_categories_v14, db)
    db.set_manager_categories = MethodType(set_manager_categories_v14, db)

    # ------------------------------- aliases: only queried for unknown prefix commands
    original_get_alias = db.get_alias
    original_add_alias = db.add_alias
    original_remove_alias = db.remove_alias

    async def get_alias_v14(_db, guild_id: int, alias: str):
        _sync_connection_epoch(bot)
        key = (int(guild_id), str(alias).casefold())
        cached = _cache_get(state["alias_cache"], key, ALIAS_CACHE_TTL)
        if cached is not _MISSING:
            return dict(cached) if isinstance(cached, dict) else None
        row = await original_get_alias(int(guild_id), str(alias).casefold())
        value = dict(row) if row is not None else None
        _cache_put(state["alias_cache"], key, value, ALIAS_CACHE_TTL)
        return dict(value) if isinstance(value, dict) else None

    async def add_alias_v14(_db, guild_id: int, alias: str, command_name: str):
        result = await original_add_alias(int(guild_id), str(alias), str(command_name))
        state["alias_cache"].pop((int(guild_id), str(alias).casefold()), None)
        return result

    async def remove_alias_v14(_db, guild_id: int, alias: str):
        result = await original_remove_alias(int(guild_id), str(alias))
        state["alias_cache"].pop((int(guild_id), str(alias).casefold()), None)
        return result

    db.get_alias = MethodType(get_alias_v14, db)
    db.add_alias = MethodType(add_alias_v14, db)
    db.remove_alias = MethodType(remove_alias_v14, db)

    state["db_patched"] = True
    logger.info(
        "V14 fast-path DB actif : bootstrap guilde, créateurs, gestionnaires et alias mis en cache."
    )


async def _bulk_ensure_guilds(bot: commands.Bot) -> int:
    """Bootstrap all connected guild rows in one SQLite transaction."""
    state = _state(bot)
    _sync_connection_epoch(bot)
    db = getattr(bot, "db", None)
    conn = getattr(db, "_conn", None)
    if db is None or conn is None:
        return 0
    guild_ids = [int(guild.id) for guild in getattr(bot, "guilds", ())]
    missing = [gid for gid in guild_ids if gid not in state["ensured_guilds"]]
    if not missing:
        return 0
    async with state["ensure_lock"]:
        _sync_connection_epoch(bot)
        missing = [gid for gid in guild_ids if gid not in state["ensured_guilds"]]
        if not missing:
            return 0
        await conn.executemany(
            "INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)",
            [(gid,) for gid in missing],
        )
        await conn.executemany(
            "INSERT OR IGNORE INTO automod_settings (guild_id) VALUES (?)",
            [(gid,) for gid in missing],
        )
        await conn.commit()
        state["ensured_guilds"].update(missing)
    return len(missing)


def _patch_ready_bootstrap(bot: commands.Bot) -> None:
    state = _state(bot)
    if state.get("ready_patched"):
        return
    current = bot.on_ready
    function = getattr(current, "__func__", current)
    if getattr(function, "_sentrix_v14_ready", False):
        state["ready_patched"] = True
        return

    async def on_ready_v14(_bot, *args, **kwargs):
        try:
            count = await _bulk_ensure_guilds(_bot)
            if count:
                logger.info("V14 : %s serveur(s) initialisé(s) en une seule transaction.", count)
        except Exception:
            # Never block Discord readiness because of an optimisation. The original
            # on_ready still contains its safe per-guild fallback.
            logger.warning("V14 : bootstrap groupé indisponible, repli normal.", exc_info=True)
        return await current(*args, **kwargs)

    on_ready_v14._sentrix_v14_ready = True
    on_ready_v14._sentrix_original = function
    bot.on_ready = MethodType(on_ready_v14, bot)
    state["ready_patched"] = True


async def _flush_command_logs(bot: commands.Bot, *, limit: int = 600) -> int:
    state = _state(bot)
    queue: deque = state["command_log_queue"]
    if not queue:
        return 0
    batch = []
    while queue and len(batch) < limit:
        batch.append(queue.popleft())
    if not batch:
        return 0

    conn = getattr(getattr(bot, "db", None), "_conn", None)
    try:
        if conn is None:
            raise RuntimeError("SQLite connection unavailable")
        await conn.executemany(
            "INSERT INTO command_logs (guild_id,user_id,command_name,timestamp) VALUES (?,?,?,?)",
            batch,
        )
        await conn.commit()
        return len(batch)
    except Exception:
        # Restore the batch in original order. Command logging is diagnostic-only; it must
        # never break an actual user command.
        for item in reversed(batch):
            queue.appendleft(item)
        mono = time.monotonic()
        if mono - float(state.get("last_log_error", 0.0)) >= 60.0:
            state["last_log_error"] = mono
            logger.warning("V14 : écriture groupée command_logs indisponible, nouvel essai prévu.", exc_info=True)
        return 0


async def _command_log_worker(bot: commands.Bot) -> None:
    await bot.wait_until_ready()
    state = _state(bot)
    event: asyncio.Event = state["command_log_event"]
    while not bot.is_closed():
        try:
            try:
                await asyncio.wait_for(event.wait(), timeout=COMMAND_LOG_FLUSH_SECONDS)
            except asyncio.TimeoutError:
                pass
            event.clear()
            while state["command_log_queue"]:
                flushed = await _flush_command_logs(bot)
                if flushed <= 0:
                    break
                if len(state["command_log_queue"]) < COMMAND_LOG_BATCH_SIZE:
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("V14 command log worker cycle failed.", exc_info=True)
            await asyncio.sleep(2.0)


def _patch_command_logging(bot: commands.Bot) -> None:
    state = _state(bot)
    if state.get("logging_patched") or not hasattr(bot, "_log_command"):
        return
    original = bot._log_command

    async def queue_command_log(_bot, ctx: commands.Context):
        if ctx.guild is None or ctx.command is None:
            return None
        queue: deque = state["command_log_queue"]
        if len(queue) >= COMMAND_LOG_MAX_QUEUE:
            queue.popleft()
            state["dropped_command_logs"] = int(state.get("dropped_command_logs", 0)) + 1
        queue.append(
            (
                int(ctx.guild.id),
                int(ctx.author.id),
                str(ctx.command.qualified_name)[:120],
                int(time.time()),
            )
        )
        if len(queue) >= COMMAND_LOG_BATCH_SIZE:
            state["command_log_event"].set()
        return None

    queue_command_log._sentrix_v14 = True
    queue_command_log._sentrix_original = original
    bot._log_command = MethodType(queue_command_log, bot)
    state["logging_patched"] = True

    if _session_started(bot) and state.get("command_log_task") is None:
        state["command_log_task"] = asyncio.create_task(
            _command_log_worker(bot), name="sentrix-v14-command-log-batcher"
        )
    logger.info("V14 : journal des commandes groupé en lots, sans commit SQLite par commande.")


async def _typing_after_delay(bot: commands.Bot, ctx: commands.Context, key: int) -> None:
    try:
        await asyncio.sleep(TYPING_DELAY_SECONDS)
        if bot.is_closed() or getattr(ctx, "interaction", None) is not None:
            return
        if getattr(ctx, "_sentrix_response_sent", False):
            return
        trigger = getattr(getattr(ctx, "channel", None), "trigger_typing", None)
        if callable(trigger):
            await trigger()
    except asyncio.CancelledError:
        raise
    except (discord.Forbidden, discord.HTTPException):
        pass
    except Exception:
        logger.debug("V14 typing indicator unavailable.", exc_info=True)
    finally:
        _state(bot)["typing_tasks"].pop(key, None)


def _install_command_experience(bot: commands.Bot) -> None:
    state = _state(bot)
    if state.get("listeners_installed"):
        return

    async def command_start(ctx: commands.Context) -> None:
        if getattr(ctx, "interaction", None) is not None:
            return
        message = getattr(ctx, "message", None)
        key = int(getattr(message, "id", 0) or id(ctx))
        old = state["typing_tasks"].pop(key, None)
        if old and not old.done():
            old.cancel()
        state["typing_tasks"][key] = asyncio.create_task(
            _typing_after_delay(bot, ctx, key), name=f"sentrix-v14-typing-{key}"
        )

    async def command_end(ctx: commands.Context, *_args) -> None:
        message = getattr(ctx, "message", None)
        key = int(getattr(message, "id", 0) or id(ctx))
        task = state["typing_tasks"].pop(key, None)
        if task and not task.done():
            task.cancel()

    async def guild_join(guild: discord.Guild) -> None:
        try:
            await bot.db.ensure_guild(guild.id)
        except Exception:
            logger.debug("V14 guild bootstrap failed for %s", guild.id, exc_info=True)

    async def guild_remove(guild: discord.Guild) -> None:
        gid = int(guild.id)
        state["ensured_guilds"].discard(gid)
        for cache_name in ("manager_cache", "manager_category_cache", "alias_cache"):
            cache = state[cache_name]
            for key in [key for key in cache if isinstance(key, tuple) and key and int(key[0]) == gid]:
                cache.pop(key, None)

    bot.add_listener(command_start, "on_command")
    bot.add_listener(command_end, "on_command_completion")
    bot.add_listener(command_end, "on_command_error")
    bot.add_listener(guild_join, "on_guild_join")
    bot.add_listener(guild_remove, "on_guild_remove")
    state["listeners_installed"] = True


async def _maintenance(bot: commands.Bot) -> None:
    await bot.wait_until_ready()
    state = _state(bot)
    while not bot.is_closed():
        try:
            _sync_connection_epoch(bot)
            _prune_cache(state["creator_cache"], CREATOR_CACHE_TTL)
            _prune_cache(state["manager_cache"], MANAGER_CACHE_TTL)
            _prune_cache(state["manager_category_cache"], MANAGER_CATEGORY_CACHE_TTL)
            _prune_cache(state["alias_cache"], ALIAS_CACHE_TTL)

            for key, task in list(state["typing_tasks"].items()):
                if task.done():
                    state["typing_tasks"].pop(key, None)

            if state["command_log_queue"]:
                await _flush_command_logs(bot)

            dropped = int(state.get("dropped_command_logs", 0))
            if dropped:
                logger.warning("V14 : %s ancien(s) log(s) de commande abandonné(s) après saturation de file.", dropped)
                state["dropped_command_logs"] = 0
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("V14 maintenance cycle failed.", exc_info=True)
        await asyncio.sleep(MAINTENANCE_SECONDS)


def install(bot: commands.Bot) -> None:
    """Install V14 once. Safe to call repeatedly from the existing runtime chain."""
    state = _state(bot)
    _patch_database_hot_paths(bot)
    _patch_ready_bootstrap(bot)
    _patch_command_logging(bot)
    _install_command_experience(bot)

    if _session_started(bot) and state.get("maintenance_task") is None:
        state["maintenance_task"] = asyncio.create_task(
            _maintenance(bot), name="sentrix-v14-maintenance"
        )

    if not state.get("installed"):
        state["installed"] = True
        logger.info(
            "SentriX V14 Core actif : fast-path DB, logs groupés et retour visuel des commandes lentes."
        )


__all__ = ["install"]
