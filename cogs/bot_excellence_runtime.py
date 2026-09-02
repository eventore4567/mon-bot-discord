"""Améliorations runtime du bot Discord SentriX, sans dépendance au dashboard.

Cette couche n'ajoute aucune commande publique. Elle renforce les systèmes existants :
- caches bornés pour les réglages IA/jeux ;
- limitation de concurrence IA et anti-abus des opérations coûteuses ;
- escalade AutoMod persistante et réellement progressive (mute -> kick -> ban) ;
- économie atomique pour rob/gamble/deposit/withdraw/sell ;
- statistiques, séries et défi quotidien des mini-jeux ;
- activité/rappels intelligents des tickets avec peu d'accès SQL ;
- déduplication durable des notifications sociales ;
- supervision des tâches de fond et réparation des vues persistantes ;
- diagnostic automatique de démarrage et des permissions critiques ;
- journalisation des incidents asyncio inattendus.

Les patches sont idempotents et installés après les cogs concernés par stability_runtime.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import random
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks

from database.db import now
from utils import embeds, helpers
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.excellence-runtime")

CACHE_TTL_SECONDS = 15.0
AI_TEXT_CONCURRENCY = 6
AI_IMAGE_CONCURRENCY = 2
AI_QUEUE_TIMEOUT = 2.0
GAME_DAILY_TARGET = 3
GAME_DAILY_BONUS = 50
TICKET_STAFF_REMINDER_SECONDS = 3600
TICKET_CACHE_REFRESH_SECONDS = 60
TICKET_ACTIVITY_FLUSH_SECONDS = 20
SUPERVISOR_INTERVAL_SECONDS = 60
VIEW_REPAIR_INTERVAL_SECONDS = 3600
HEALTH_SNAPSHOT_INTERVAL_SECONDS = 900
RISK_WINDOW_SECONDS = 3600
RISK_LEVEL_DECAY_SECONDS = 86400

RUNTIME_SCHEMA = """
CREATE TABLE IF NOT EXISTS runtime_incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    guild_id INTEGER,
    detail TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runtime_incidents_time
ON runtime_incidents (created_at);

CREATE TABLE IF NOT EXISTS runtime_health_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    guild_count INTEGER NOT NULL DEFAULT 0,
    member_count INTEGER NOT NULL DEFAULT 0,
    cog_count INTEGER NOT NULL DEFAULT 0,
    persistent_view_count INTEGER NOT NULL DEFAULT 0,
    db_ok INTEGER NOT NULL DEFAULT 0,
    missing_permissions_json TEXT NOT NULL DEFAULT '{}',
    background_loops_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runtime_health_time
ON runtime_health_snapshots (created_at);

CREATE TABLE IF NOT EXISTS automod_risk_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    weight INTEGER NOT NULL DEFAULT 1,
    reason TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_automod_risk_lookup
ON automod_risk_events (guild_id, user_id, created_at);

CREATE TABLE IF NOT EXISTS automod_risk_state (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    sanction_level INTEGER NOT NULL DEFAULT 0,
    last_action_at INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS economy_action_cooldowns (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    last_used_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id, action)
);

CREATE TABLE IF NOT EXISTS game_outcomes (
    session_id TEXT PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    game_name TEXT NOT NULL,
    result TEXT NOT NULL,
    reward_amount INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_game_outcomes_user_time
ON game_outcomes (guild_id, user_id, created_at);

CREATE TABLE IF NOT EXISTS game_player_stats (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    game_name TEXT NOT NULL,
    plays INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    draws INTEGER NOT NULL DEFAULT 0,
    total_rewards INTEGER NOT NULL DEFAULT 0,
    current_streak INTEGER NOT NULL DEFAULT 0,
    best_streak INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, game_name)
);
CREATE INDEX IF NOT EXISTS idx_game_player_stats_rank
ON game_player_stats (guild_id, wins DESC, total_rewards DESC);

CREATE TABLE IF NOT EXISTS game_daily_progress (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    wins INTEGER NOT NULL DEFAULT 0,
    claimed INTEGER NOT NULL DEFAULT 0,
    claimed_at INTEGER,
    PRIMARY KEY (guild_id, user_id, day)
);

CREATE TABLE IF NOT EXISTS ticket_response_state (
    ticket_id INTEGER PRIMARY KEY,
    last_user_at INTEGER NOT NULL DEFAULT 0,
    last_staff_at INTEGER NOT NULL DEFAULT 0,
    last_staff_reminder_at INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ticket_runtime_reminders (
    ticket_id INTEGER NOT NULL,
    last_activity_at INTEGER NOT NULL,
    reminder_type TEXT NOT NULL,
    reminded_at INTEGER NOT NULL,
    PRIMARY KEY (ticket_id, last_activity_at, reminder_type)
);

CREATE TABLE IF NOT EXISTS social_notification_deliveries (
    subscription_id INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    item_url TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (subscription_id, item_id)
);
CREATE INDEX IF NOT EXISTS idx_social_delivery_status_time
ON social_notification_deliveries (status, updated_at);
"""


class RuntimeRateLimitError(commands.CheckFailure):
    def __init__(self, retry_after: float):
        self.retry_after = max(1.0, float(retry_after))
        super().__init__("Opération coûteuse temporairement limitée.")


_AI_CACHE_PATCHED = False
_GAME_CACHE_PATCHED = False
_AI_CONCURRENCY_PATCHED = False
_AUTOMOD_PATCHED = False
_GAME_STATS_PATCHED = False
_MINIGAMES_PATCHED = False
_SOCIAL_DEDUPE_PATCHED = False
_ECONOMY_PATCHED = False
_ERROR_HANDLER_PATCHED = False

_AI_SETTINGS_CACHE: dict[tuple[int, int], tuple[float, dict]] = {}
_GAME_SETTINGS_CACHE: dict[tuple[int, int], tuple[float, dict]] = {}
_AI_TEXT_SEMAPHORE = asyncio.Semaphore(AI_TEXT_CONCURRENCY)
_AI_IMAGE_SEMAPHORE = asyncio.Semaphore(AI_IMAGE_CONCURRENCY)
_AI_ACTIVE_USERS: set[int] = set()
_RESOURCE_BUCKETS: dict[tuple[int, int, str], deque[float]] = defaultdict(deque)
_AUTOMOD_LOCKS: dict[tuple[int, int], asyncio.Lock] = {}

_RESOURCE_LIMITS: dict[str, tuple[int, float]] = {
    "image": (1, 45.0),
    "code": (2, 30.0),
    "ai": (4, 20.0),
    "tickettranscript": (2, 60.0),
    "server-backup": (1, 120.0),
    "server-restore": (1, 300.0),
    "create-server": (1, 300.0),
    "wipe-server": (1, 600.0),
}


def _session_started(bot: commands.Bot) -> bool:
    return bool(getattr(getattr(bot, "http", None), "token", None))


async def _ensure_schema(bot: commands.Bot) -> bool:
    state = getattr(bot, "_sentrix_excellence_state", None)
    if state is None:
        state = {}
        bot._sentrix_excellence_state = state
    if state.get("schema_ready"):
        return True
    conn = getattr(getattr(bot, "db", None), "_conn", None)
    if conn is None:
        return False
    await conn.executescript(RUNTIME_SCHEMA)
    await conn.commit()
    state["schema_ready"] = True
    return True


async def _record_incident(bot: commands.Bot, source: str, detail: str, guild_id: int | None = None) -> None:
    try:
        if not await _ensure_schema(bot):
            return
        await bot.db.execute(
            "INSERT INTO runtime_incidents (source,guild_id,detail,created_at) VALUES (?,?,?,?)",
            (str(source)[:120], guild_id, str(detail)[:1800], now()),
        )
    except Exception:
        logger.exception("Impossible d'enregistrer un incident runtime.")


def _install_settings_caches() -> None:
    global _AI_CACHE_PATCHED, _GAME_CACHE_PATCHED

    if not _AI_CACHE_PATCHED:
        from utils import ai_service

        current_get = ai_service.get_settings
        current_update = ai_service.update_setting
        if not getattr(current_get, "_sentrix_cached", False):
            async def cached_ai_settings(bot, guild_id: int):
                key = (id(bot), int(guild_id))
                stamp, value = _AI_SETTINGS_CACHE.get(key, (0.0, None))
                if value is not None and time.monotonic() - stamp < CACHE_TTL_SECONDS:
                    return copy.deepcopy(value)
                value = await current_get(bot, guild_id)
                _AI_SETTINGS_CACHE[key] = (time.monotonic(), copy.deepcopy(value))
                return value

            async def update_ai_setting(bot, guild_id: int, field: str, value):
                result = await current_update(bot, guild_id, field, value)
                _AI_SETTINGS_CACHE.pop((id(bot), int(guild_id)), None)
                return result

            cached_ai_settings._sentrix_cached = True
            update_ai_setting._sentrix_cache_invalidator = True
            ai_service.get_settings = cached_ai_settings
            ai_service.update_setting = update_ai_setting
        _AI_CACHE_PATCHED = True
        logger.info("Cache des réglages IA activé (%ss).", CACHE_TTL_SECONDS)

    if not _GAME_CACHE_PATCHED:
        from utils import game_rewards

        current_get = game_rewards.get_settings
        current_set = game_rewards.set_settings
        if not getattr(current_get, "_sentrix_cached", False):
            async def cached_game_settings(bot, guild_id: int):
                key = (id(bot), int(guild_id))
                stamp, value = _GAME_SETTINGS_CACHE.get(key, (0.0, None))
                if value is not None and time.monotonic() - stamp < CACHE_TTL_SECONDS:
                    return copy.deepcopy(value)
                value = await current_get(bot, guild_id)
                _GAME_SETTINGS_CACHE[key] = (time.monotonic(), copy.deepcopy(value))
                return value

            async def set_game_settings(bot, guild_id: int, updates: dict):
                result = await current_set(bot, guild_id, updates)
                _GAME_SETTINGS_CACHE.pop((id(bot), int(guild_id)), None)
                return result

            cached_game_settings._sentrix_cached = True
            set_game_settings._sentrix_cache_invalidator = True
            game_rewards.get_settings = cached_game_settings
            game_rewards.set_settings = set_game_settings
        _GAME_CACHE_PATCHED = True
        logger.info("Cache des réglages mini-jeux activé (%ss).", CACHE_TTL_SECONDS)


def _install_ai_concurrency() -> None:
    global _AI_CONCURRENCY_PATCHED
    if _AI_CONCURRENCY_PATCHED:
        return

    from utils import ai_service

    current_generate = ai_service.generate
    current_image = ai_service.generate_image
    if getattr(current_generate, "_sentrix_concurrency_guard", False):
        _AI_CONCURRENCY_PATCHED = True
        return

    async def guarded_generate(*args, **kwargs):
        user_id = kwargs.get("user_id")
        active_key = int(user_id) if user_id is not None else None
        if active_key is not None and active_key in _AI_ACTIVE_USERS:
            return ai_service.AiResult(
                error=ai_service.ERROR_RATE_LIMIT,
                model_key=kwargs.get("model_key", ai_service.MODEL_TERRA),
            )
        acquired = False
        if active_key is not None:
            _AI_ACTIVE_USERS.add(active_key)
        try:
            try:
                await asyncio.wait_for(_AI_TEXT_SEMAPHORE.acquire(), timeout=AI_QUEUE_TIMEOUT)
                acquired = True
            except asyncio.TimeoutError:
                return ai_service.AiResult(
                    error=ai_service.ERROR_RATE_LIMIT,
                    model_key=kwargs.get("model_key", ai_service.MODEL_TERRA),
                )
            return await current_generate(*args, **kwargs)
        finally:
            if acquired:
                _AI_TEXT_SEMAPHORE.release()
            if active_key is not None:
                _AI_ACTIVE_USERS.discard(active_key)

    async def guarded_image(*args, **kwargs):
        acquired = False
        try:
            try:
                await asyncio.wait_for(_AI_IMAGE_SEMAPHORE.acquire(), timeout=AI_QUEUE_TIMEOUT)
                acquired = True
            except asyncio.TimeoutError:
                return ai_service.ImageResult(error=ai_service.ERROR_RATE_LIMIT, model=getattr(ai_service.config, "OPENAI_IMAGE_MODEL", None))
            return await current_image(*args, **kwargs)
        finally:
            if acquired:
                _AI_IMAGE_SEMAPHORE.release()

    guarded_generate._sentrix_concurrency_guard = True
    guarded_image._sentrix_concurrency_guard = True
    ai_service.generate = guarded_generate
    ai_service.generate_image = guarded_image
    _AI_CONCURRENCY_PATCHED = True
    logger.info(
        "Protection IA activée : %s requêtes texte et %s images concurrentes maximum.",
        AI_TEXT_CONCURRENCY,
        AI_IMAGE_CONCURRENCY,
    )


async def _resource_guard(ctx: commands.Context) -> bool:
    command = getattr(ctx, "command", None)
    if command is None:
        return True
    root = command.root_parent or command
    name = str(root.name).casefold()
    limit = _RESOURCE_LIMITS.get(name)
    if limit is None:
        return True

    rate, period = limit
    key = (int(getattr(getattr(ctx, "guild", None), "id", 0) or 0), int(ctx.author.id), name)
    bucket = _RESOURCE_BUCKETS[key]
    moment = time.monotonic()
    while bucket and moment - bucket[0] >= period:
        bucket.popleft()
    if len(bucket) >= rate:
        raise RuntimeRateLimitError(period - (moment - bucket[0]))
    bucket.append(moment)

    if len(_RESOURCE_BUCKETS) > 10000:
        stale = []
        for candidate, stamps in _RESOURCE_BUCKETS.items():
            if not stamps or moment - stamps[-1] > 900:
                stale.append(candidate)
        for candidate in stale[:5000]:
            _RESOURCE_BUCKETS.pop(candidate, None)
    return True


async def _record_game_outcome(
    bot: commands.Bot,
    guild_id: int,
    user_id: int,
    game_name: str,
    session_id: str,
    result: str,
    reward_amount: int,
) -> int:
    """Enregistre une manche une seule fois et retourne l'éventuel bonus du défi quotidien."""
    if not await _ensure_schema(bot):
        return 0
    db = bot.db
    conn = db._conn
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = str(result or "loss").casefold()
    if result not in {"win", "loss", "draw"}:
        result = "loss"

    async with db._economy_lock:
        cursor = await conn.execute(
            "INSERT OR IGNORE INTO game_outcomes "
            "(session_id,guild_id,user_id,game_name,result,reward_amount,created_at) VALUES (?,?,?,?,?,?,?)",
            (session_id, guild_id, user_id, game_name, result, max(0, int(reward_amount or 0)), now()),
        )
        if cursor.rowcount < 1:
            await conn.commit()
            return 0

        row = await conn.execute(
            "SELECT plays,wins,losses,draws,total_rewards,current_streak,best_streak "
            "FROM game_player_stats WHERE guild_id=? AND user_id=? AND game_name=?",
            (guild_id, user_id, game_name),
        )
        current = await row.fetchone()
        plays = int(current[0] if current else 0) + 1
        wins = int(current[1] if current else 0) + (1 if result == "win" else 0)
        losses = int(current[2] if current else 0) + (1 if result == "loss" else 0)
        draws = int(current[3] if current else 0) + (1 if result == "draw" else 0)
        total_rewards = int(current[4] if current else 0) + max(0, int(reward_amount or 0))
        previous_streak = int(current[5] if current else 0)
        previous_best = int(current[6] if current else 0)
        streak = previous_streak + 1 if result == "win" else 0
        best = max(previous_best, streak)
        await conn.execute(
            "INSERT INTO game_player_stats "
            "(guild_id,user_id,game_name,plays,wins,losses,draws,total_rewards,current_streak,best_streak,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(guild_id,user_id,game_name) DO UPDATE SET "
            "plays=excluded.plays,wins=excluded.wins,losses=excluded.losses,draws=excluded.draws,"
            "total_rewards=excluded.total_rewards,current_streak=excluded.current_streak,"
            "best_streak=excluded.best_streak,updated_at=excluded.updated_at",
            (guild_id, user_id, game_name, plays, wins, losses, draws, total_rewards, streak, best, now()),
        )

        bonus = 0
        if result == "win":
            await conn.execute(
                "INSERT INTO game_daily_progress (guild_id,user_id,day,wins,claimed) VALUES (?,?,?,1,0) "
                "ON CONFLICT(guild_id,user_id,day) DO UPDATE SET wins=wins+1",
                (guild_id, user_id, day),
            )
            progress_cur = await conn.execute(
                "SELECT wins,claimed FROM game_daily_progress WHERE guild_id=? AND user_id=? AND day=?",
                (guild_id, user_id, day),
            )
            progress = await progress_cur.fetchone()
            if progress and int(progress[0]) >= GAME_DAILY_TARGET and not int(progress[1]):
                claimed = await conn.execute(
                    "UPDATE game_daily_progress SET claimed=1,claimed_at=? "
                    "WHERE guild_id=? AND user_id=? AND day=? AND claimed=0",
                    (now(), guild_id, user_id, day),
                )
                if claimed.rowcount > 0:
                    bonus = GAME_DAILY_BONUS
                    await conn.execute(
                        "INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)",
                        (guild_id, user_id),
                    )
                    await conn.execute(
                        "UPDATE economy SET cash=cash+? WHERE guild_id=? AND user_id=?",
                        (bonus, guild_id, user_id),
                    )
                    await conn.execute(
                        "INSERT INTO economy_transactions "
                        "(guild_id,sender_id,receiver_id,transaction_type,amount,created_at,reason) "
                        "VALUES (?,NULL,?,'game_daily_challenge',?,?,?)",
                        (guild_id, user_id, bonus, now(), f"Défi quotidien : {GAME_DAILY_TARGET} victoires"),
                    )
        await conn.commit()
        return bonus


def _install_game_statistics() -> None:
    global _GAME_STATS_PATCHED
    if _GAME_STATS_PATCHED:
        return
    from utils import game_rewards

    current = game_rewards.reward_game_winner
    if getattr(current, "_sentrix_stats", False):
        _GAME_STATS_PATCHED = True
        return

    async def reward_with_stats(
        bot,
        guild_id: int,
        user_id: int,
        game_name: str,
        base_amount: int,
        session_id: str,
        result: str = "win",
        metadata: dict | None = None,
    ):
        reward = await current(
            bot,
            guild_id,
            user_id,
            game_name,
            base_amount,
            session_id,
            result=result,
            metadata=metadata,
        )
        if getattr(reward, "reason", "") != "already_rewarded":
            bonus = await _record_game_outcome(
                bot,
                int(guild_id),
                int(user_id),
                str(game_name),
                str(session_id),
                str(result),
                int(getattr(reward, "amount", 0) or 0),
            )
            if bonus:
                reward.metadata = dict(getattr(reward, "metadata", {}) or {})
                reward.metadata["daily_challenge_bonus"] = bonus
        return reward

    reward_with_stats._sentrix_stats = True
    game_rewards.reward_game_winner = reward_with_stats
    _GAME_STATS_PATCHED = True
    logger.info("Mini-jeux : statistiques, séries et défi quotidien activés.")


def _install_minigame_outcomes(bot: commands.Bot) -> None:
    global _MINIGAMES_PATCHED
    cog = bot.get_cog("Minigames")
    if cog is None or _MINIGAMES_PATCHED:
        return
    cls = type(cog)
    current_finish = cls._finish
    if not getattr(current_finish, "_sentrix_outcomes", False):
        async def finish_with_outcomes(self, ctx, game_name, session_id, result, base_amount):
            reward = await current_finish(self, ctx, game_name, session_id, result, base_amount)
            if result != "win" and ctx.guild is not None:
                await _record_game_outcome(
                    self.bot,
                    ctx.guild.id,
                    ctx.author.id,
                    game_name,
                    session_id,
                    result,
                    0,
                )
            return reward

        finish_with_outcomes._sentrix_outcomes = True
        cls._finish = finish_with_outcomes

    current_line = cls._reward_line
    if not getattr(current_line, "_sentrix_daily_challenge", False):
        def reward_line_with_challenge(reward):
            text = current_line(reward)
            bonus = 0
            if reward is not None:
                bonus = int((getattr(reward, "metadata", {}) or {}).get("daily_challenge_bonus", 0) or 0)
            if bonus > 0:
                text += f"\nDéfi quotidien terminé : +{bonus} crédits."
            return text

        reward_line_with_challenge._sentrix_daily_challenge = True
        cls._reward_line = staticmethod(reward_line_with_challenge)

    _MINIGAMES_PATCHED = True
    logger.info("Mini-jeux : résultats perdus/nuls historisés et défi affiché au gagnant.")


async def _atomic_rob(bot, guild_id: int, thief_id: int, target_id: int, cooldown: int):
    db = bot.db
    conn = db._conn
    async with db._economy_lock:
        await conn.execute("INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)", (guild_id, thief_id))
        await conn.execute("INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)", (guild_id, target_id))
        cooldown_cur = await conn.execute(
            "SELECT last_used_at FROM economy_action_cooldowns WHERE guild_id=? AND user_id=? AND action='rob'",
            (guild_id, thief_id),
        )
        cooldown_row = await cooldown_cur.fetchone()
        current_time = now()
        if cooldown_row:
            remaining = int(cooldown) - (current_time - int(cooldown_row[0]))
            if remaining > 0:
                await conn.commit()
                return "cooldown", remaining, 0
        await conn.execute(
            "INSERT INTO economy_action_cooldowns (guild_id,user_id,action,last_used_at) VALUES (?,?,'rob',?) "
            "ON CONFLICT(guild_id,user_id,action) DO UPDATE SET last_used_at=excluded.last_used_at",
            (guild_id, thief_id, current_time),
        )
        target_cur = await conn.execute(
            "SELECT cash FROM economy WHERE guild_id=? AND user_id=?", (guild_id, target_id)
        )
        target_cash = int((await target_cur.fetchone())[0])
        if target_cash < 50:
            await conn.commit()
            return "target_poor", 0, 0

        if random.random() < 0.4:
            amount = random.randint(1, min(target_cash, 300))
            await conn.execute(
                "UPDATE economy SET cash=cash-? WHERE guild_id=? AND user_id=? AND cash>=?",
                (amount, guild_id, target_id, amount),
            )
            await conn.execute(
                "UPDATE economy SET cash=cash+? WHERE guild_id=? AND user_id=?",
                (amount, guild_id, thief_id),
            )
            await conn.execute(
                "INSERT INTO economy_transactions "
                "(guild_id,sender_id,receiver_id,transaction_type,amount,created_at,reason) "
                "VALUES (?,?,?,'rob',?,?,?)",
                (guild_id, target_id, thief_id, amount, current_time, "Vol réussi"),
            )
            await conn.commit()
            return "success", 0, amount

        thief_cur = await conn.execute(
            "SELECT cash FROM economy WHERE guild_id=? AND user_id=?", (guild_id, thief_id)
        )
        thief_cash = max(0, int((await thief_cur.fetchone())[0]))
        penalty = min(random.randint(20, 100), thief_cash)
        if penalty > 0:
            await conn.execute(
                "UPDATE economy SET cash=MAX(0,cash-?) WHERE guild_id=? AND user_id=?",
                (penalty, guild_id, thief_id),
            )
            await conn.execute(
                "INSERT INTO economy_transactions "
                "(guild_id,sender_id,receiver_id,transaction_type,amount,created_at,reason) "
                "VALUES (?, ?, NULL, 'rob_fail', ?, ?, ?)",
                (guild_id, thief_id, penalty, current_time, "Vol raté, amende"),
            )
        await conn.commit()
        return "failure", 0, penalty


def _install_economy_atomicity(bot: commands.Bot) -> None:
    global _ECONOMY_PATCHED
    if _ECONOMY_PATCHED:
        return
    cog = bot.get_cog("Economy")
    if cog is None:
        return

    from . import economy as economy_mod
    from utils import stats_service

    cls = type(cog)
    rob_command = bot.get_command("rob")
    if rob_command is not None and not getattr(rob_command.callback, "_sentrix_atomic", False):
        async def robust_rob(self, ctx: commands.Context, membre: discord.Member):
            if membre.id == ctx.author.id:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Vous ne pouvez pas vous voler vous-même.')))
            if membre.bot:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Vous ne pouvez pas voler un bot.')))
            status, remaining, amount = await _atomic_rob(
                self.bot, ctx.guild.id, ctx.author.id, membre.id, economy_mod.ROB_COOLDOWN
            )
            if status == "cooldown":
                minutes = max(1, (remaining + 59) // 60)
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(f'Vous devez attendre encore {minutes} minute(s) avant de retenter un vol.')))
            if status == "target_poor":
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(f"{membre.display_name} n'a pas assez d'argent liquide à voler.")))
            if status == "success":
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Vous avez volé **{stats_service.format_number(amount)}** crédits à {membre.display_name}.')))
            if amount > 0:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f"Vous avez été attrapé et payé **{stats_service.format_number(amount)}** crédits d'amende.")))
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Vous avez été attrapé, mais votre portefeuille était vide.')))

        robust_rob._sentrix_atomic = True
        rob_command.callback = robust_rob

    gamble_command = bot.get_command("gamble")
    if gamble_command is not None and not getattr(gamble_command.callback, "_sentrix_atomic", False):
        async def robust_gamble(self, ctx: commands.Context, montant: int):
            if montant <= 0:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Le montant doit être positif.')))
            db = self.bot.db
            conn = db._conn
            async with db._economy_lock:
                await conn.execute("INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)", (ctx.guild.id, ctx.author.id))
                cur = await conn.execute("SELECT cash FROM economy WHERE guild_id=? AND user_id=?", (ctx.guild.id, ctx.author.id))
                cash = int((await cur.fetchone())[0])
                if cash < montant:
                    await conn.commit()
                    enough = False
                    won = False
                else:
                    enough = True
                    won = random.random() < 0.5
                    delta = montant if won else -montant
                    await conn.execute(
                        "UPDATE economy SET cash=MAX(0,cash+?) WHERE guild_id=? AND user_id=?",
                        (delta, ctx.guild.id, ctx.author.id),
                    )
                    await conn.execute(
                        "INSERT INTO economy_transactions "
                        "(guild_id,sender_id,receiver_id,transaction_type,amount,created_at,reason) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (
                            ctx.guild.id,
                            None if won else ctx.author.id,
                            ctx.author.id if won else None,
                            "gamble_win" if won else "gamble_loss",
                            montant,
                            now(),
                            "Casino",
                        ),
                    )
                    await conn.commit()
            if not enough:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Vous n'avez pas assez d'argent.")))
            text = "gagné" if won else "perdu"
            response = embeds.success if won else embeds.error
            await ctx.send(embed=response(f"Vous avez {text} **{stats_service.format_number(montant)}** crédits."))

        robust_gamble._sentrix_atomic = True
        gamble_command.callback = robust_gamble

    current_deposit = cls._deposit_to_bank
    if not getattr(current_deposit, "_sentrix_atomic", False):
        async def atomic_deposit(self, ctx: commands.Context, montant: str):
            db = self.bot.db
            conn = db._conn
            async with db._economy_lock:
                await conn.execute("INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)", (ctx.guild.id, ctx.author.id))
                cur = await conn.execute("SELECT cash FROM economy WHERE guild_id=? AND user_id=?", (ctx.guild.id, ctx.author.id))
                cash = int((await cur.fetchone())[0])
                amount = economy_mod._parse_amount(montant, cash)
                if amount is None or amount <= 0 or amount > cash:
                    await conn.commit()
                    valid = False
                else:
                    valid = True
                    await conn.execute(
                        "UPDATE economy SET cash=cash-?,bank=bank+? WHERE guild_id=? AND user_id=? AND cash>=?",
                        (amount, amount, ctx.guild.id, ctx.author.id, amount),
                    )
                    await conn.commit()
            if not valid:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Montant invalide. Utilisez un nombre positif ou `all`.')))
            await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'{stats_service.format_number(amount)} crédits transférés dans votre banque.')))

        atomic_deposit._sentrix_atomic = True
        cls._deposit_to_bank = atomic_deposit

    withdraw_command = bot.get_command("withdraw")
    if withdraw_command is not None and not getattr(withdraw_command.callback, "_sentrix_atomic", False):
        async def atomic_withdraw(self, ctx: commands.Context, montant: str):
            db = self.bot.db
            conn = db._conn
            async with db._economy_lock:
                await conn.execute("INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)", (ctx.guild.id, ctx.author.id))
                cur = await conn.execute("SELECT bank FROM economy WHERE guild_id=? AND user_id=?", (ctx.guild.id, ctx.author.id))
                bank = int((await cur.fetchone())[0])
                amount = economy_mod._parse_amount(montant, bank)
                if amount is None or amount <= 0 or amount > bank:
                    await conn.commit()
                    valid = False
                else:
                    valid = True
                    await conn.execute(
                        "UPDATE economy SET cash=cash+?,bank=bank-? WHERE guild_id=? AND user_id=? AND bank>=?",
                        (amount, amount, ctx.guild.id, ctx.author.id, amount),
                    )
                    await conn.commit()
            if not valid:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Montant invalide.')))
            await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'{stats_service.format_number(amount)} crédits retirés de la banque.')))

        atomic_withdraw._sentrix_atomic = True
        withdraw_command.callback = atomic_withdraw

    sell_command = bot.get_command("sell")
    if sell_command is not None and not getattr(sell_command.callback, "_sentrix_atomic", False):
        async def atomic_sell(self, ctx: commands.Context, *, objet: str):
            db = self.bot.db
            conn = db._conn
            async with db._economy_lock:
                item_cur = await conn.execute(
                    "SELECT quantity FROM inventory WHERE guild_id=? AND user_id=? AND item_name=?",
                    (ctx.guild.id, ctx.author.id, objet),
                )
                owned = await item_cur.fetchone()
                if not owned or int(owned[0]) < 1:
                    await conn.commit()
                    sale = None
                else:
                    shop_cur = await conn.execute(
                        "SELECT price FROM shop_items WHERE guild_id=? AND name=?", (ctx.guild.id, objet)
                    )
                    shop = await shop_cur.fetchone()
                    price = int(int(shop[0]) * 0.5) if shop else 10
                    changed = await conn.execute(
                        "UPDATE inventory SET quantity=quantity-1 "
                        "WHERE guild_id=? AND user_id=? AND item_name=? AND quantity>0",
                        (ctx.guild.id, ctx.author.id, objet),
                    )
                    if changed.rowcount < 1:
                        await conn.commit()
                        sale = None
                    else:
                        await conn.execute("INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)", (ctx.guild.id, ctx.author.id))
                        await conn.execute(
                            "UPDATE economy SET cash=cash+? WHERE guild_id=? AND user_id=?",
                            (price, ctx.guild.id, ctx.author.id),
                        )
                        await conn.execute(
                            "INSERT INTO economy_transactions "
                            "(guild_id,sender_id,receiver_id,transaction_type,amount,created_at,reason) "
                            "VALUES (?,NULL,?,'sell',?,?,?)",
                            (ctx.guild.id, ctx.author.id, price, now(), f"Vente : {objet}"),
                        )
                        await conn.commit()
                        sale = price
            if sale is None:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Vous ne possédez pas cet objet.')))
            await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Vous avez vendu **{objet}** pour {stats_service.format_number(sale)} crédits.')))

        atomic_sell._sentrix_atomic = True
        sell_command.callback = atomic_sell

    _ECONOMY_PATCHED = True
    logger.info("Économie : rob, gamble, banque et vente rendus atomiques et anti-solde négatif.")


def _risk_weight(reason: str) -> int:
    value = (reason or "").casefold()
    severe = ("scam", "arnaque", "phishing", "malware", "insulte", "multilingue", "menace", "raid")
    return 2 if any(marker in value for marker in severe) else 1


def _install_persistent_automod(bot: commands.Bot) -> None:
    global _AUTOMOD_PATCHED
    cog = bot.get_cog("Automod")
    if cog is None or _AUTOMOD_PATCHED:
        return
    cls = type(cog)
    current = cls._maybe_escalate
    if getattr(current, "_sentrix_persistent_progressive", False):
        _AUTOMOD_PATCHED = True
        return

    async def progressive_escalation(self, guild: discord.Guild, member: discord.Member, reason: str):
        if member.id == guild.owner_id or member.id in getattr(__import__("config"), "OWNER_IDS", []):
            return None, 0
        conf = await self.get_automod_cached(guild.id)
        if not conf.get("escalation", 1):
            return None, 0
        if not await _ensure_schema(self.bot):
            return await current(self, guild, member, reason)

        key = (guild.id, member.id)
        lock = _AUTOMOD_LOCKS.setdefault(key, asyncio.Lock())
        async with lock:
            stamp = now()
            weight = _risk_weight(reason)
            await self.bot.db.execute(
                "DELETE FROM automod_risk_events WHERE created_at < ?",
                (stamp - RISK_WINDOW_SECONDS,),
            )
            await self.bot.db.execute(
                "INSERT INTO automod_risk_events (guild_id,user_id,weight,reason,created_at) VALUES (?,?,?,?,?)",
                (guild.id, member.id, weight, str(reason)[:700], stamp),
            )
            score_row = await self.bot.db.fetchone(
                "SELECT COUNT(*) AS hits,COALESCE(SUM(weight),0) AS score FROM automod_risk_events "
                "WHERE guild_id=? AND user_id=? AND created_at>=?",
                (guild.id, member.id, stamp - RISK_WINDOW_SECONDS),
            )
            hits = int(score_row["hits"] if score_row else 0)
            score = int(score_row["score"] if score_row else 0)
            state = await self.bot.db.fetchone(
                "SELECT sanction_level,last_action_at FROM automod_risk_state WHERE guild_id=? AND user_id=?",
                (guild.id, member.id),
            )
            level = int(state["sanction_level"] if state else 0)
            last_action = int(state["last_action_at"] if state else 0)
            if last_action and stamp - last_action > RISK_LEVEL_DECAY_SECONDS:
                level = 0

            # Après le mute, deux nouvelles infractions suffisent pour passer au kick,
            # puis deux autres pour le ban. Contrairement à l'ancien compteur remis à zéro,
            # les niveaux de sanction persistent donc réellement entre deux séries.
            threshold = 3 if level <= 0 else 2
            if score < threshold:
                await self.bot.db.execute(
                    "INSERT INTO automod_risk_state (guild_id,user_id,sanction_level,last_action_at,updated_at) "
                    "VALUES (?,?,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET "
                    "sanction_level=excluded.sanction_level,updated_at=excluded.updated_at",
                    (guild.id, member.id, level, last_action, stamp),
                )
                return None, hits

            me = guild.me
            if me is None or member.top_role >= me.top_role:
                return None, hits

            action = "mute" if level <= 0 else ("kick" if level == 1 else "ban")
            action_reason = f"AutoMod progressif : {hits} infraction(s), score {score} — {reason}"
            try:
                if action == "mute":
                    await member.timeout(discord.utils.utcnow() + timedelta(minutes=10), reason=action_reason)
                elif action == "kick":
                    await member.kick(reason=action_reason)
                else:
                    await member.ban(reason=action_reason, delete_message_seconds=0)
            except (discord.Forbidden, discord.HTTPException):
                return None, hits

            new_level = min(3, level + 1)
            await self.bot.db.execute(
                "INSERT INTO automod_risk_state (guild_id,user_id,sanction_level,last_action_at,updated_at) "
                "VALUES (?,?,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET "
                "sanction_level=excluded.sanction_level,last_action_at=excluded.last_action_at,updated_at=excluded.updated_at",
                (guild.id, member.id, new_level, stamp, stamp),
            )
            await self.bot.db.execute(
                "DELETE FROM automod_risk_events WHERE guild_id=? AND user_id=?",
                (guild.id, member.id),
            )
            try:
                await self.bot.db.record_sanction(
                    guild.id,
                    member.id,
                    int(getattr(getattr(self.bot, "user", None), "id", 0) or 0),
                    action,
                    action_reason,
                    600 if action == "mute" else None,
                )
            except Exception:
                logger.exception("Impossible d'historiser la sanction AutoMod progressive.")
            return action, hits

    progressive_escalation._sentrix_persistent_progressive = True
    cls._maybe_escalate = progressive_escalation
    _AUTOMOD_PATCHED = True
    logger.info("AutoMod : escalade persistante et progressive mute -> kick -> ban activée.")


async def _reserve_social_delivery(bot: commands.Bot, subscription_id: int, item_id: str, item_url: str) -> bool:
    if not await _ensure_schema(bot):
        return True
    stamp = now()
    stale_before = stamp - 600
    cur = await bot.db.execute(
        "INSERT OR IGNORE INTO social_notification_deliveries "
        "(subscription_id,item_id,status,item_url,created_at,updated_at) VALUES (?,?,'pending',?,?,?)",
        (subscription_id, item_id, item_url, stamp, stamp),
    )
    if cur.rowcount > 0:
        return True
    row = await bot.db.fetchone(
        "SELECT status,updated_at FROM social_notification_deliveries WHERE subscription_id=? AND item_id=?",
        (subscription_id, item_id),
    )
    if row and row["status"] == "sent":
        return False
    changed = await bot.db.execute(
        "UPDATE social_notification_deliveries SET status='pending',item_url=?,updated_at=? "
        "WHERE subscription_id=? AND item_id=? AND status!='sent' AND updated_at<?",
        (item_url, stamp, subscription_id, item_id, stale_before),
    )
    return changed.rowcount > 0


def _install_social_dedupe(bot: commands.Bot) -> None:
    global _SOCIAL_DEDUPE_PATCHED
    cog = bot.get_cog("Notifications")
    if cog is None or _SOCIAL_DEDUPE_PATCHED:
        return
    from . import notifications as notifications_mod

    cls = type(cog)
    current = cls._check_subscription
    if getattr(current, "_sentrix_durable_dedupe", False):
        _SOCIAL_DEDUPE_PATCHED = True
        return

    async def check_subscription_durable(self, row):
        guild = self.bot.get_guild(row["guild_id"])
        if guild is None:
            return
        channel = guild.get_channel(row["discord_channel_id"])
        role = guild.get_role(row["role_id"])
        if channel is None or role is None:
            await self.bot.db.execute("UPDATE social_notifications SET enabled=0 WHERE id=?", (row["id"],))
            return
        try:
            item = await notifications_mod._extract_latest(row["source_url"])
        except Exception:
            logger.warning("Lecture sociale impossible pour #%s.", row["id"], exc_info=True)
            return
        if not item or not item.get("id"):
            return
        item_id = str(item["id"])
        if not row["last_item_id"]:
            await self._update_last_item(row["id"], item_id, row["source_url"])
            return
        if item_id == str(row["last_item_id"]):
            return

        platform = row["platform"]
        link = notifications_mod._item_url(platform, row["source_url"], item)
        if not await _reserve_social_delivery(self.bot, int(row["id"]), item_id, link):
            # Si un autre worker l'a déjà envoyé, réaligne le curseur local afin de ne pas
            # redécouvrir la même publication à chaque boucle.
            sent = await self.bot.db.fetchone(
                "SELECT status FROM social_notification_deliveries WHERE subscription_id=? AND item_id=?",
                (row["id"], item_id),
            )
            if sent and sent["status"] == "sent":
                await self._update_last_item(row["id"], item_id, link)
            return

        title = (item.get("title") or f"Nouvelle publication sur {platform}")[:256]
        description = row["custom_text"] or "Une nouvelle publication vient d'être mise en ligne."
        notification = discord.Embed(
            title=title,
            description=description,
            color=notifications_mod._platform_details(row["source_url"])[1],
        )
        notification.add_field(name="Voir la publication", value=f"[Ouvrir sur {platform}]({link})", inline=False)
        notification.set_footer(text=f"Notification automatique SentriX • {platform}")
        image_url = row["image_url"] or item.get("thumbnail")
        if image_url and notifications_mod._valid_https_url(image_url):
            notification.set_image(url=image_url)
        try:
            await channel.send(
                content=role.mention,
                embed=notification,
                allowed_mentions=discord.AllowedMentions(everyone=False, users=False, roles=[role], replied_user=False),
            )
        except discord.HTTPException:
            await self.bot.db.execute(
                "DELETE FROM social_notification_deliveries WHERE subscription_id=? AND item_id=? AND status='pending'",
                (row["id"], item_id),
            )
            logger.warning("Notification sociale #%s non envoyée : nouvelle tentative prévue.", row["id"], exc_info=True)
            return

        await self.bot.db.execute(
            "UPDATE social_notification_deliveries SET status='sent',updated_at=? WHERE subscription_id=? AND item_id=?",
            (now(), row["id"], item_id),
        )
        await self._update_last_item(row["id"], item_id, link)

    check_subscription_durable._sentrix_durable_dedupe = True
    cls._check_subscription = check_subscription_durable
    _SOCIAL_DEDUPE_PATCHED = True
    logger.info("Notifications sociales : déduplication durable et reprise après redémarrage activées.")


def _ticket_message_listener(bot: commands.Bot):
    async def on_message(message: discord.Message):
        if message.guild is None or message.author.bot:
            return
        state = getattr(bot, "_sentrix_excellence_state", {})
        ticket_channels = state.get("ticket_channels", {})
        meta = ticket_channels.get(message.channel.id)
        if not meta:
            return
        stamp = now()
        pending = state.setdefault("ticket_activity_pending", {})
        entry = pending.setdefault(meta["ticket_id"], {
            "channel_id": message.channel.id,
            "last_activity": 0,
            "last_user": 0,
            "last_staff": 0,
        })
        entry["last_activity"] = max(entry["last_activity"], stamp)
        author = message.author
        is_staff = False
        if isinstance(author, discord.Member):
            is_staff = bool(author.guild_permissions.manage_channels)
            staff_role_id = meta.get("staff_role_id")
            if staff_role_id and any(role.id == staff_role_id for role in author.roles):
                is_staff = True
            if meta.get("claimed_by") == author.id:
                is_staff = True
        if author.id == meta["user_id"]:
            entry["last_user"] = max(entry["last_user"], stamp)
        elif is_staff:
            entry["last_staff"] = max(entry["last_staff"], stamp)
    return on_message


async def _refresh_ticket_cache(bot: commands.Bot) -> None:
    state = bot._sentrix_excellence_state
    rows = await bot.db.fetchall(
        "SELECT t.id,t.channel_id,t.user_id,t.claimed_by,t.last_activity_at,tt.staff_role_id,tt.autoclose_hours "
        "FROM tickets t LEFT JOIN ticket_types tt ON tt.id=t.type_id WHERE t.status='ouvert'"
    )
    state["ticket_channels"] = {
        int(row["channel_id"]): {
            "ticket_id": int(row["id"]),
            "user_id": int(row["user_id"]),
            "claimed_by": row["claimed_by"],
            "staff_role_id": row["staff_role_id"],
            "autoclose_hours": int(row["autoclose_hours"] or 0),
            "last_activity_at": int(row["last_activity_at"] or 0),
        }
        for row in rows if row["channel_id"]
    }


async def _flush_ticket_activity(bot: commands.Bot) -> None:
    state = bot._sentrix_excellence_state
    pending = state.get("ticket_activity_pending", {})
    if not pending:
        return
    state["ticket_activity_pending"] = {}
    for ticket_id, entry in pending.items():
        try:
            if entry["last_activity"]:
                await bot.db.execute(
                    "UPDATE tickets SET last_activity_at=? WHERE id=? AND status='ouvert'",
                    (entry["last_activity"], ticket_id),
                )
            await bot.db.execute(
                "INSERT INTO ticket_response_state "
                "(ticket_id,last_user_at,last_staff_at,last_staff_reminder_at,updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(ticket_id) DO UPDATE SET "
                "last_user_at=MAX(last_user_at,excluded.last_user_at),"
                "last_staff_at=MAX(last_staff_at,excluded.last_staff_at),updated_at=excluded.updated_at",
                (ticket_id, entry["last_user"], entry["last_staff"], 0, now()),
            )
        except Exception:
            logger.exception("Échec du flush d'activité du ticket #%s.", ticket_id)


async def _ticket_reminders(bot: commands.Bot) -> None:
    stamp = now()
    rows = await bot.db.fetchall(
        "SELECT t.id,t.guild_id,t.channel_id,t.user_id,t.last_activity_at,t.claimed_by,"
        "tt.autoclose_hours,tt.staff_role_id,trs.last_user_at,trs.last_staff_at,trs.last_staff_reminder_at "
        "FROM tickets t LEFT JOIN ticket_types tt ON tt.id=t.type_id "
        "LEFT JOIN ticket_response_state trs ON trs.ticket_id=t.id "
        "WHERE t.status='ouvert'"
    )
    for row in rows:
        guild = bot.get_guild(row["guild_id"])
        channel = guild.get_channel(row["channel_id"]) if guild else None
        if guild is None or channel is None:
            await bot.db.execute("UPDATE tickets SET status='supprime' WHERE id=?", (row["id"],))
            continue

        last_user = int(row["last_user_at"] or 0)
        last_staff = int(row["last_staff_at"] or 0)
        last_staff_reminder = int(row["last_staff_reminder_at"] or 0)
        if last_user and last_user > last_staff and stamp - last_user >= TICKET_STAFF_REMINDER_SECONDS and last_staff_reminder < last_user:
            role = guild.get_role(row["staff_role_id"]) if row["staff_role_id"] else None
            content = (
                f"{role.mention} " if role else ""
            ) + "Ce ticket attend une réponse du staff depuis plus d'une heure."
            try:
                await channel.send(
                    content,
                    allowed_mentions=discord.AllowedMentions(
                        everyone=False,
                        users=False,
                        roles=[role] if role else False,
                        replied_user=False,
                    ),
                )
                await bot.db.execute(
                    "UPDATE ticket_response_state SET last_staff_reminder_at=?,updated_at=? WHERE ticket_id=?",
                    (stamp, stamp, row["id"]),
                )
            except discord.HTTPException:
                pass

        autoclose_hours = int(row["autoclose_hours"] or 0)
        last_activity = int(row["last_activity_at"] or 0)
        if autoclose_hours <= 0 or last_activity <= 0:
            continue
        close_after = autoclose_hours * 3600
        elapsed = stamp - last_activity
        reminder_after = max(300, int(close_after * 0.75))
        if elapsed < reminder_after or elapsed >= close_after:
            continue
        reserved = await bot.db.execute(
            "INSERT OR IGNORE INTO ticket_runtime_reminders "
            "(ticket_id,last_activity_at,reminder_type,reminded_at) VALUES (?,?, 'preclose', ?)",
            (row["id"], last_activity, stamp),
        )
        if reserved.rowcount < 1:
            continue
        remaining = max(1, (close_after - elapsed + 3599) // 3600)
        try:
            await channel.send(
                f"Ce ticket est inactif. Sans nouvelle réponse, il sera fermé automatiquement dans environ {remaining} heure(s)."
            )
        except discord.HTTPException:
            await bot.db.execute(
                "DELETE FROM ticket_runtime_reminders WHERE ticket_id=? AND last_activity_at=? AND reminder_type='preclose'",
                (row["id"], last_activity),
            )


async def _repair_persistent_views(bot: commands.Bot) -> dict:
    result = {"ticket_panels": 0, "generic_views": 0}
    try:
        from .tickets import TicketControlView
        if not getattr(bot, "_sentrix_excellence_ticket_control_view", False):
            bot.add_view(TicketControlView())
            bot._sentrix_excellence_ticket_control_view = True
            result["generic_views"] += 1
        tickets_cog = bot.get_cog("Tickets")
        if tickets_cog is not None:
            result["ticket_panels"] = int(await tickets_cog.restore_panel_views() or 0)
    except Exception:
        await _record_incident(bot, "persistent_views:tickets", "Réparation impossible")

    try:
        from .economy import ShopRoleView
        if not getattr(bot, "_sentrix_shop_view_registered", False):
            bot.add_view(ShopRoleView(persistent_handler=True))
            bot._sentrix_shop_view_registered = True
            result["generic_views"] += 1
    except Exception:
        pass

    try:
        from .verification import VerifyView
        if not getattr(bot, "_sentrix_excellence_verify_view", False):
            bot.add_view(VerifyView())
            bot._sentrix_excellence_verify_view = True
            result["generic_views"] += 1
    except Exception:
        pass

    try:
        from .events import GiveawayView
        if not getattr(bot, "_sentrix_excellence_giveaway_view", False):
            bot.add_view(GiveawayView())
            bot._sentrix_excellence_giveaway_view = True
            result["generic_views"] += 1
    except Exception:
        pass
    return result


def _background_loop_status(bot: commands.Bot) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for cog_name, cog in bot.cogs.items():
        for attr_name in dir(cog):
            try:
                value = getattr(cog, attr_name)
            except Exception:
                continue
            if not isinstance(value, tasks.Loop):
                continue
            task = value.get_task()
            key = f"{cog_name}.{attr_name}"
            if task is None:
                statuses[key] = "not_started"
            elif task.cancelled():
                statuses[key] = "cancelled"
            elif task.done():
                statuses[key] = "failed" if value.failed() else "stopped"
            else:
                statuses[key] = "running"
    return statuses


async def _restart_failed_loops(bot: commands.Bot) -> int:
    restarted = 0
    for cog_name, cog in list(bot.cogs.items()):
        for attr_name in dir(cog):
            try:
                value = getattr(cog, attr_name)
            except Exception:
                continue
            if not isinstance(value, tasks.Loop):
                continue
            task = value.get_task()
            # Ne démarre jamais une boucle que le cog n'avait jamais lancée volontairement.
            if task is None or not task.done() or bot.is_closed():
                continue
            try:
                value.start()
                restarted += 1
                await _record_incident(
                    bot,
                    "background_loop_restart",
                    f"{cog_name}.{attr_name} redémarrée automatiquement",
                )
            except Exception as exc:
                await _record_incident(
                    bot,
                    "background_loop_restart_failed",
                    f"{cog_name}.{attr_name}: {type(exc).__name__}: {exc}",
                )
    return restarted


async def _guild_permission_issues(guild: discord.Guild) -> list[str]:
    me = guild.me
    if me is None:
        return ["membre_bot_introuvable"]
    permissions = me.guild_permissions
    required = (
        "view_channel", "send_messages", "embed_links", "read_message_history",
        "manage_messages", "manage_channels", "manage_roles", "moderate_members",
        "kick_members", "ban_members", "view_audit_log",
    )
    return [name for name in required if not getattr(permissions, name, False)]


async def _health_snapshot(bot: commands.Bot) -> None:
    if not await _ensure_schema(bot):
        return
    db_ok = 0
    try:
        await bot.db.fetchone("SELECT 1 AS ok")
        db_ok = 1
    except Exception as exc:
        await _record_incident(bot, "database_health", f"{type(exc).__name__}: {exc}")

    missing: dict[str, list[str]] = {}
    for guild in bot.guilds:
        issues = await _guild_permission_issues(guild)
        if issues:
            missing[str(guild.id)] = issues
    loops = _background_loop_status(bot)
    persistent_views = len(getattr(bot, "persistent_views", []) or [])
    await bot.db.execute(
        "INSERT INTO runtime_health_snapshots "
        "(latency_ms,guild_count,member_count,cog_count,persistent_view_count,db_ok,missing_permissions_json,background_loops_json,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            helpers.latence_ms(bot),
            len(bot.guilds),
            sum(int(g.member_count or 0) for g in bot.guilds),
            len(bot.cogs),
            persistent_views,
            db_ok,
            json.dumps(missing, separators=(",", ":")),
            json.dumps(loops, separators=(",", ":")),
            now(),
        ),
    )
    if missing:
        logger.warning("Diagnostic permissions : %s serveur(s) ont au moins une permission recommandée manquante.", len(missing))
    logger.info(
        "Diagnostic runtime : DB=%s, %s cogs, %s vues persistantes, latence=%sms.",
        "OK" if db_ok else "ERREUR",
        len(bot.cogs),
        persistent_views,
        helpers.latence_ms(bot),
    )


async def _maintenance_loop(bot: commands.Bot) -> None:
    await bot.wait_until_ready()
    state = bot._sentrix_excellence_state
    state["last_view_repair"] = 0
    state["last_health_snapshot"] = 0
    state["last_ticket_cache"] = 0
    state["last_ticket_flush"] = 0
    state["last_ticket_reminders"] = 0

    await _refresh_ticket_cache(bot)
    await _flush_ticket_activity(bot)
    await _repair_persistent_views(bot)
    await _health_snapshot(bot)

    while not bot.is_closed():
        stamp = time.monotonic()
        try:
            await _restart_failed_loops(bot)
            if stamp - state.get("last_ticket_cache", 0) >= TICKET_CACHE_REFRESH_SECONDS:
                await _refresh_ticket_cache(bot)
                state["last_ticket_cache"] = stamp
            if stamp - state.get("last_ticket_flush", 0) >= TICKET_ACTIVITY_FLUSH_SECONDS:
                await _flush_ticket_activity(bot)
                state["last_ticket_flush"] = stamp
            if stamp - state.get("last_ticket_reminders", 0) >= 300:
                await _ticket_reminders(bot)
                state["last_ticket_reminders"] = stamp
            if stamp - state.get("last_view_repair", 0) >= VIEW_REPAIR_INTERVAL_SECONDS:
                await _repair_persistent_views(bot)
                state["last_view_repair"] = stamp
            if stamp - state.get("last_health_snapshot", 0) >= HEALTH_SNAPSHOT_INTERVAL_SECONDS:
                await _health_snapshot(bot)
                state["last_health_snapshot"] = stamp
            await bot.db.execute("DELETE FROM runtime_incidents WHERE created_at < ?", (now() - 30 * 86400,))
            await bot.db.execute("DELETE FROM social_notification_deliveries WHERE status='sent' AND updated_at < ?", (now() - 14 * 86400,))
            await bot.db.execute("DELETE FROM ticket_runtime_reminders WHERE reminded_at < ?", (now() - 30 * 86400,))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Erreur de maintenance Excellence.")
            await _record_incident(bot, "excellence_maintenance", f"{type(exc).__name__}: {exc}")
        await asyncio.sleep(SUPERVISOR_INTERVAL_SECONDS)


def _install_asyncio_exception_handler(bot: commands.Bot) -> None:
    state = bot._sentrix_excellence_state
    if state.get("asyncio_handler") or not _session_started(bot):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    previous = loop.get_exception_handler()

    def handler(event_loop, context):
        message = str(context.get("message") or "Exception asyncio non gérée")
        exception = context.get("exception")
        detail = message
        if exception is not None:
            detail += f" | {type(exception).__name__}: {exception}"
        try:
            event_loop.create_task(_record_incident(bot, "asyncio", detail))
        except Exception:
            pass
        if previous is not None:
            previous(event_loop, context)
        else:
            event_loop.default_exception_handler(context)

    loop.set_exception_handler(handler)
    state["asyncio_handler"] = True


async def _matchmake_tictactoe(ctx: commands.Context) -> None:
    bot = ctx.bot
    if ctx.guild is None:
        return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Le matchmaking fonctionne uniquement sur un serveur.')))
    cog = bot.get_cog("Minigames")
    if cog is None:
        return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Les mini-jeux sont temporairement indisponibles.')))
    from utils import game_rewards
    role_ids = {role.id for role in getattr(ctx.author, "roles", [])}
    allowed, reason = await game_rewards.is_game_enabled(bot, ctx.guild.id, "tictactoe", ctx.channel.id, role_ids)
    if not allowed:
        return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(reason)))

    queue = getattr(bot, "_sentrix_tictactoe_matchmaking", None)
    if queue is None:
        queue = {}
        bot._sentrix_tictactoe_matchmaking = queue
    key = (ctx.guild.id, ctx.channel.id)
    stamp = time.monotonic()
    waiting = queue.get(key)
    if waiting and stamp - waiting[1] > 120:
        queue.pop(key, None)
        waiting = None
    if waiting and waiting[0] == ctx.author.id:
        return await panels.envoyer(ctx, panels.depuis_embed(embeds.info("Vous êtes déjà en attente d'un adversaire dans ce salon.")))
    if waiting:
        first = ctx.guild.get_member(waiting[0])
        queue.pop(key, None)
        if first is None or first.bot:
            queue[key] = (ctx.author.id, stamp)
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.info("Recherche d'un adversaire dans ce salon. Un autre membre peut taper `+tictactoe`.")))
        from .minigames import TicTacToeView
        session_id = game_rewards.new_session_id("tictactoe")
        view = TicTacToeView(first, ctx.author, cog=cog, session_id=session_id)
        embed = await cog._embed(
            ctx.guild.id,
            title="Morpion",
            description=f"{first.mention} contre {ctx.author.mention}.\nAu tour de {first.mention}.",
        )
        return await ctx.send(embed=embed, view=view)
    queue[key] = (ctx.author.id, stamp)
    await panels.envoyer(ctx, panels.depuis_embed(embeds.info("Recherche d'un adversaire dans ce salon. Un autre membre peut taper `+tictactoe` sans mention pour rejoindre la partie.")))


def _install_error_handler(bot: commands.Bot) -> None:
    global _ERROR_HANDLER_PATCHED
    cls = type(bot)
    if _ERROR_HANDLER_PATCHED or getattr(cls.on_command_error, "_sentrix_excellence", False):
        _ERROR_HANDLER_PATCHED = True
        return
    original = cls.on_command_error

    async def improved_error_handler(self, ctx: commands.Context, error: commands.CommandError):
        original_error = getattr(error, "original", error)
        if isinstance(original_error, RuntimeRateLimitError):
            seconds = max(1, round(original_error.retry_after))
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(f'Cette fonction est temporairement limitée pour protéger SentriX. Réessayez dans environ {seconds} seconde(s).')))
        if (
            isinstance(original_error, commands.MissingRequiredArgument)
            and ctx.command is not None
            and ctx.command.qualified_name == "tictactoe"
            and getattr(original_error.param, "name", "") == "adversaire"
        ):
            return await _matchmake_tictactoe(ctx)
        return await original(self, ctx, error)

    improved_error_handler._sentrix_excellence = True
    improved_error_handler._sentrix_original = original
    cls.on_command_error = improved_error_handler
    _ERROR_HANDLER_PATCHED = True
    logger.info("Erreurs commandes : limite anti-abus lisible et matchmaking morpion sans argument activés.")


async def _on_guild_join_diagnostic(bot: commands.Bot, guild: discord.Guild) -> None:
    try:
        issues = await _guild_permission_issues(guild)
        if issues:
            await _record_incident(
                bot,
                "guild_permissions",
                "Permissions recommandées manquantes : " + ", ".join(issues),
                guild.id,
            )
    except Exception as exc:
        await _record_incident(bot, "guild_join_diagnostic", f"{type(exc).__name__}: {exc}", guild.id)


def _install_listeners_and_tasks(bot: commands.Bot) -> None:
    state = bot._sentrix_excellence_state
    if not state.get("resource_guard"):
        bot.add_check(_resource_guard)
        state["resource_guard"] = True
    if not state.get("ticket_listener"):
        bot.add_listener(_ticket_message_listener(bot), "on_message")
        state["ticket_listener"] = True
    if not state.get("guild_join_listener"):
        async def guild_join(guild: discord.Guild):
            await _on_guild_join_diagnostic(bot, guild)
        bot.add_listener(guild_join, "on_guild_join")
        state["guild_join_listener"] = True

    _install_asyncio_exception_handler(bot)
    if _session_started(bot) and not state.get("maintenance_task"):
        state["maintenance_task"] = asyncio.create_task(
            _maintenance_loop(bot), name="sentrix-excellence-maintenance"
        )


async def install(bot: commands.Bot, extension_name: str = "") -> None:
    """Installe progressivement les renforcements à mesure que les cogs sont chargés."""
    if not hasattr(bot, "_sentrix_excellence_state"):
        bot._sentrix_excellence_state = {
            "schema_ready": False,
            "ticket_channels": {},
            "ticket_activity_pending": {},
        }

    await _ensure_schema(bot)
    _install_settings_caches()
    _install_ai_concurrency()
    _install_game_statistics()
    _install_persistent_automod(bot)
    _install_minigame_outcomes(bot)
    _install_social_dedupe(bot)
    _install_economy_atomicity(bot)
    _install_error_handler(bot)
    _install_listeners_and_tasks(bot)

    logger.debug("Excellence runtime vérifié après %s.", extension_name or "extension")
