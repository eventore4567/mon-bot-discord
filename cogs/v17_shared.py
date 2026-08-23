"""Socle partagé de SentriX V17.

Cette couche n'efface ni ne renomme aucune donnée historique. Elle fournit aux modules V17 :
- un schéma additif pour la modération, sécurité, tickets, IA, économie, missions et santé ;
- des appels Discord avec retry uniquement sur erreurs serveur temporaires et opérations sûres ;
- une invalidation automatique du cache guild_config après toute écriture SQL directe ;
- un cache très court des décisions de permission dépendant du rôle de modération ;
- des snapshots serveur JSON réutilisables avant les opérations destructives ;
- un crédit économique atomique et historisé pour succès/missions/saisons.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from types import MethodType
from typing import Any, Awaitable, Callable, TypeVar

import discord
from discord.ext import commands

from database.db import now

logger = logging.getLogger("bot.v17-shared")
T = TypeVar("T")

PERMISSION_CACHE_TTL = 5.0
MAX_PERMISSION_CACHE = 20000

V17_SCHEMA = """
CREATE TABLE IF NOT EXISTS v17_protected_members (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    reason TEXT,
    added_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS v17_case_proofs (
    guild_id INTEGER NOT NULL,
    case_number INTEGER NOT NULL,
    proof TEXT NOT NULL,
    added_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, case_number)
);

CREATE TABLE IF NOT EXISTS v17_staff_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    note TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_v17_staff_notes_user
ON v17_staff_notes (guild_id, user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS v17_mod_undo (
    guild_id INTEGER NOT NULL,
    case_number INTEGER NOT NULL,
    undone_by INTEGER NOT NULL,
    detail TEXT,
    undone_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, case_number)
);

CREATE TABLE IF NOT EXISTS v17_sanction_policy (
    guild_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    mute_warns INTEGER NOT NULL DEFAULT 3,
    tempban_warns INTEGER NOT NULL DEFAULT 5,
    ban_warns INTEGER NOT NULL DEFAULT 7,
    mute_seconds INTEGER NOT NULL DEFAULT 3600,
    tempban_seconds INTEGER NOT NULL DEFAULT 86400,
    updated_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS v17_sanction_escalations (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    level TEXT NOT NULL,
    warning_count INTEGER NOT NULL,
    triggered_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id, level)
);

CREATE TABLE IF NOT EXISTS v17_suspicious_accounts (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    reasons_json TEXT NOT NULL DEFAULT '[]',
    joined_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_v17_suspicious_score
ON v17_suspicious_accounts (guild_id, score DESC, joined_at DESC);

CREATE TABLE IF NOT EXISTS v17_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    data_json TEXT NOT NULL,
    created_by INTEGER,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_v17_snapshots_guild
ON v17_snapshots (guild_id, created_at DESC);

CREATE TABLE IF NOT EXISTS v17_antinuke_whitelist (
    guild_id INTEGER NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    added_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, subject_type, subject_id, action)
);

CREATE TABLE IF NOT EXISTS v17_lockdown_state (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    send_messages_state INTEGER,
    saved_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS v17_log_event_settings (
    guild_id INTEGER NOT NULL,
    event_key TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (guild_id, event_key)
);

CREATE TABLE IF NOT EXISTS v17_ticket_settings (
    guild_id INTEGER PRIMARY KEY,
    reopen_minutes INTEGER NOT NULL DEFAULT 15,
    updated_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS v17_ticket_claim_events (
    ticket_id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    staff_id INTEGER NOT NULL,
    claimed_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_v17_ticket_claim_staff
ON v17_ticket_claim_events (guild_id, staff_id, claimed_at DESC);

CREATE TABLE IF NOT EXISTS v17_ai_channel_memory (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    memory_minutes INTEGER NOT NULL DEFAULT 30,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS v17_ai_role_quotas (
    guild_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    daily_limit INTEGER NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS v17_ai_context (
    guild_id INTEGER PRIMARY KEY,
    context_text TEXT NOT NULL DEFAULT '',
    updated_by INTEGER,
    updated_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS v17_shop_rules (
    guild_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    stock INTEGER NOT NULL DEFAULT -1,
    sale_price INTEGER,
    sale_ends_at INTEGER,
    available_from INTEGER,
    available_until INTEGER,
    updated_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, item_id)
);

CREATE TABLE IF NOT EXISTS v17_achievements (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    achievement_key TEXT NOT NULL,
    reward INTEGER NOT NULL DEFAULT 0,
    unlocked_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id, achievement_key)
);

CREATE TABLE IF NOT EXISTS v17_activity_counters (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    period_kind TEXT NOT NULL,
    period_key TEXT NOT NULL,
    commands_count INTEGER NOT NULL DEFAULT 0,
    games_count INTEGER NOT NULL DEFAULT 0,
    economy_count INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, period_kind, period_key)
);

CREATE TABLE IF NOT EXISTS v17_mission_claims (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    period_kind TEXT NOT NULL,
    period_key TEXT NOT NULL,
    mission_key TEXT NOT NULL,
    reward INTEGER NOT NULL DEFAULT 0,
    claimed_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id, period_kind, period_key, mission_key)
);

CREATE TABLE IF NOT EXISTS v17_seasons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    starts_at INTEGER NOT NULL,
    ends_at INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_v17_seasons_active
ON v17_seasons (guild_id, active, ends_at);

CREATE TABLE IF NOT EXISTS v17_season_points (
    season_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    points INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (season_id, user_id)
);

CREATE TABLE IF NOT EXISTS v17_command_health (
    guild_id INTEGER NOT NULL,
    command_name TEXT NOT NULL,
    hour_bucket INTEGER NOT NULL,
    calls INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    total_ms REAL NOT NULL DEFAULT 0,
    max_ms REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, command_name, hour_bucket)
);
CREATE INDEX IF NOT EXISTS idx_v17_command_health_time
ON v17_command_health (hour_bucket DESC);
"""


def state(bot: commands.Bot) -> dict[str, Any]:
    value = getattr(bot, "_sentrix_v17_state", None)
    if not isinstance(value, dict):
        value = {
            "schema_ready": False,
            "permission_cache": {},
            "permission_patch": False,
            "execute_patch": False,
            "installed_modules": set(),
            "command_started": {},
            "health_alerts": {},
            "join_windows": {},
            "sanction_recent": {},
            "economy_buckets": {},
            "season_message_cooldowns": {},
        }
        bot._sentrix_v17_state = value
    return value


async def ensure_schema(bot: commands.Bot) -> bool:
    runtime = state(bot)
    if runtime.get("schema_ready"):
        return True
    conn = getattr(getattr(bot, "db", None), "_conn", None)
    if conn is None:
        return False
    await conn.executescript(V17_SCHEMA)
    await conn.commit()
    runtime["schema_ready"] = True
    return True


async def safe_discord_call(
    factory: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.35,
) -> T:
    """Retente seulement les erreurs HTTP Discord 5xx, jamais les refus/404/400.

    Cette fonction est réservée aux opérations idempotentes ou explicitement protégées
    contre les doublons par V17. Elle ne rejoue jamais arbitrairement une commande entière.
    """
    last: Exception | None = None
    for index in range(max(1, attempts)):
        try:
            return await factory()
        except discord.HTTPException as exc:
            last = exc
            status = int(getattr(exc, "status", 0) or 0)
            if status < 500 or index >= attempts - 1:
                raise
            await asyncio.sleep(base_delay * (2 ** index))
    assert last is not None
    raise last


def invalidate_permission_cache(bot: commands.Bot, guild_id: int | None = None) -> None:
    cache = state(bot)["permission_cache"]
    if guild_id is None:
        cache.clear()
        return
    gid = int(guild_id)
    for key in [key for key in cache if key and int(key[0]) == gid]:
        cache.pop(key, None)


def install_config_invalidation(bot: commands.Bot) -> None:
    runtime = state(bot)
    if runtime.get("execute_patch"):
        return
    db = getattr(bot, "db", None)
    if db is None:
        return
    current = db.execute
    if getattr(current, "_sentrix_v17_config_invalidation", False):
        runtime["execute_patch"] = True
        return

    async def execute_v17(_db, query: str, params: tuple = ()):
        result = await current(query, params)
        text = str(query or "").lstrip().casefold()
        if "guild_config" in text and text.startswith(("update", "insert", "delete", "replace")):
            try:
                _db._guild_config_cache.clear()
            except Exception:
                pass
            invalidate_permission_cache(bot)
        return result

    execute_v17._sentrix_v17_config_invalidation = True
    execute_v17._sentrix_original = current
    db.execute = MethodType(execute_v17, db)
    runtime["execute_patch"] = True
    logger.info("V17 : invalidation immédiate du cache guild_config après écritures SQL directes.")


def install_permission_cache(bot: commands.Bot) -> None:
    runtime = state(bot)
    if runtime.get("permission_patch"):
        return
    from utils import checks

    current = checks.is_mod_or_permission
    if getattr(current, "_sentrix_v17_permission_cache", False):
        runtime["permission_patch"] = True
        return

    async def cached_is_mod_or_permission(ctx: commands.Context, permission: str) -> bool:
        member = ctx.author if isinstance(ctx.author, discord.Member) else None
        if member is None or ctx.guild is None:
            return False
        role_signature = tuple(sorted(role.id for role in member.roles))
        key = (ctx.guild.id, member.id, str(permission), role_signature)
        cache = state(bot)["permission_cache"]
        item = cache.get(key)
        mono = time.monotonic()
        if item is not None and mono - float(item[0]) <= PERMISSION_CACHE_TTL:
            return bool(item[1])
        result = bool(await current(ctx, permission))
        cache[key] = (mono, result)
        if len(cache) > MAX_PERMISSION_CACHE:
            cutoff = mono - PERMISSION_CACHE_TTL * 3
            for candidate, value in list(cache.items()):
                if float(value[0]) < cutoff:
                    cache.pop(candidate, None)
            while len(cache) > MAX_PERMISSION_CACHE:
                cache.pop(next(iter(cache)))
        return result

    cached_is_mod_or_permission._sentrix_v17_permission_cache = True
    cached_is_mod_or_permission._sentrix_original = current
    checks.is_mod_or_permission = cached_is_mod_or_permission
    runtime["permission_patch"] = True
    logger.info("V17 : cache court des décisions rôle staff/permissions activé.")


def _serialize_overwrites(channel: discord.abc.GuildChannel) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for target, overwrite in getattr(channel, "overwrites", {}).items():
        allow, deny = overwrite.pair()
        result.append({
            "type": "role" if isinstance(target, discord.Role) else "member",
            "id": int(target.id),
            "allow": int(allow.value),
            "deny": int(deny.value),
        })
    return result


def snapshot_payload(guild: discord.Guild) -> dict[str, Any]:
    roles = []
    for role in guild.roles:
        if role.is_default() or role.managed:
            continue
        roles.append({
            "id": role.id,
            "name": role.name,
            "permissions": int(role.permissions.value),
            "colour": int(role.colour.value),
            "hoist": bool(role.hoist),
            "mentionable": bool(role.mentionable),
            "position": int(role.position),
        })
    channels = []
    for channel in guild.channels:
        data: dict[str, Any] = {
            "id": channel.id,
            "name": channel.name,
            "type": str(channel.type),
            "position": int(channel.position),
            "category_id": getattr(channel, "category_id", None),
            "overwrites": _serialize_overwrites(channel),
        }
        if isinstance(channel, discord.TextChannel):
            data.update({
                "topic": channel.topic,
                "slowmode_delay": channel.slowmode_delay,
                "nsfw": channel.nsfw,
            })
        elif isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            data.update({
                "bitrate": getattr(channel, "bitrate", None),
                "user_limit": getattr(channel, "user_limit", None),
            })
        channels.append(data)
    return {
        "version": 17,
        "guild_id": guild.id,
        "guild_name": guild.name,
        "created_at": now(),
        "everyone_permissions": int(guild.default_role.permissions.value),
        "roles": roles,
        "channels": channels,
    }


async def create_snapshot(
    bot: commands.Bot,
    guild: discord.Guild,
    label: str,
    created_by: int | None,
) -> int | None:
    if not await ensure_schema(bot):
        return None
    payload = snapshot_payload(guild)
    cur = await bot.db.execute(
        "INSERT INTO v17_snapshots (guild_id,label,data_json,created_by,created_at) VALUES (?,?,?,?,?)",
        (guild.id, str(label)[:120], json.dumps(payload, ensure_ascii=False), created_by, now()),
    )
    return int(cur.lastrowid)


async def award_credits(
    bot: commands.Bot,
    guild_id: int,
    user_id: int,
    amount: int,
    transaction_type: str,
    reason: str,
) -> bool:
    amount = int(amount)
    if amount <= 0:
        return False
    db = bot.db
    conn = getattr(db, "_conn", None)
    if conn is None:
        return False
    async with db._economy_lock:
        await conn.execute(
            "INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)",
            (int(guild_id), int(user_id)),
        )
        await conn.execute(
            "UPDATE economy SET cash=cash+? WHERE guild_id=? AND user_id=?",
            (amount, int(guild_id), int(user_id)),
        )
        await conn.execute(
            "INSERT INTO economy_transactions "
            "(guild_id,sender_id,receiver_id,transaction_type,amount,created_at,reason) "
            "VALUES (?,NULL,?,?,?,?,?)",
            (int(guild_id), int(user_id), str(transaction_type)[:60], amount, now(), str(reason)[:300]),
        )
        await conn.commit()
    return True


def register_command_policy(
    *,
    public: set[str] | tuple[str, ...] = (),
    moderation: set[str] | tuple[str, ...] = (),
    security: set[str] | tuple[str, ...] = (),
    tickets: set[str] | tuple[str, ...] = (),
    economy: set[str] | tuple[str, ...] = (),
    ai: set[str] | tuple[str, ...] = (),
    configuration: set[str] | tuple[str, ...] = (),
) -> None:
    """Ajoute les racines V17 à la politique fail-closed de main.py avant son audit final."""
    main = sys.modules.get("main") or sys.modules.get("__main__")
    if main is None or not hasattr(main, "PUBLIC_COMMANDS"):
        return
    main.PUBLIC_COMMANDS = frozenset(set(main.PUBLIC_COMMANDS) | {str(x).casefold() for x in public})
    categories = dict(getattr(main, "CATEGORY_COMMANDS", {}) or {})
    additions = {
        "moderation": moderation,
        "securite": security,
        "tickets": tickets,
        "economie": economy,
        "ai": ai,
        "configuration": configuration,
    }
    for category, names in additions.items():
        categories[category] = frozenset(set(categories.get(category, ())) | {str(x).casefold() for x in names})
    main.CATEGORY_COMMANDS = categories
    main.KNOWN_PERMISSION_COMMANDS = (
        main.PUBLIC_COMMANDS
        | main.OWNER_ONLY_COMMANDS
        | main.CUSTOM_PERMISSION_COMMANDS
        | frozenset(main.DISCORD_PERMISSION_COMMANDS)
        | frozenset().union(*categories.values())
    )


async def is_protected(bot: commands.Bot, guild_id: int, user_id: int) -> tuple[bool, str | None]:
    if not await ensure_schema(bot):
        return False, None
    row = await bot.db.fetchone(
        "SELECT reason FROM v17_protected_members WHERE guild_id=? AND user_id=?",
        (int(guild_id), int(user_id)),
    )
    return (row is not None, (row["reason"] if row else None))


__all__ = [
    "V17_SCHEMA",
    "award_credits",
    "create_snapshot",
    "ensure_schema",
    "install_config_invalidation",
    "install_permission_cache",
    "invalidate_permission_cache",
    "is_protected",
    "register_command_policy",
    "safe_discord_call",
    "snapshot_payload",
    "state",
]
