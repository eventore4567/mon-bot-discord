"""Suivi facultatif des sessions vocales du membre (pas d'enregistrement audio).

Les états ne dépendent pas du module XP. La base principale du bot (Postgres
en production) conserve le salon et l'heure de connexion entre redémarrages.
Les journaux publics de vocal restent configurés séparément dans log_config.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import discord

logger = logging.getLogger("bot.voice-history")

_SETTINGS = """
CREATE TABLE IF NOT EXISTS member_voice_history_settings (
    guild_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    track_moves INTEGER NOT NULL DEFAULT 1,
    track_duration INTEGER NOT NULL DEFAULT 1
)
"""
_SESSIONS = """
CREATE TABLE IF NOT EXISTS member_voice_history_sessions (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    started_at INTEGER NOT NULL,
    channel_started_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id,user_id)
)
"""
_TOTALS = """
CREATE TABLE IF NOT EXISTS member_voice_history_totals (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    seconds INTEGER NOT NULL DEFAULT 0,
    completed_sessions INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id,user_id)
)
"""
_schema_lock = asyncio.Lock()

@dataclass(frozen=True)
class VoiceTransition:
    kind: str
    channel_before: int | None
    channel_after: int | None
    duration_seconds: int | None = None
    segment_seconds: int | None = None
    # Whether this movement must be added to the private dossier if no
    # live vocal log was sent to the configured Discord log channel.
    archive: bool = True


async def ensure_schema(bot) -> None:
    # Attach readiness to the database object, never to its reusable id().
    # In test suites, short-lived databases can reuse ids and skip migrations.
    if getattr(bot.db, "_voice_history_schema_ready", False):
        return
    async with _schema_lock:
        if getattr(bot.db, "_voice_history_schema_ready", False):
            return
        for statement in (_SETTINGS, _SESSIONS, _TOTALS):
            await bot.db.execute(statement)
        setattr(bot.db, "_voice_history_schema_ready", True)


async def get_settings(bot, guild_id: int) -> dict:
    await ensure_schema(bot)
    row = await bot.db.fetchone(
        "SELECT enabled,track_moves,track_duration FROM member_voice_history_settings "
        "WHERE guild_id=?", (int(guild_id),),
    )
    return {
        "enabled": bool(row["enabled"]) if row else False,
        "track_moves": bool(row["track_moves"]) if row else True,
        "track_duration": bool(row["track_duration"]) if row else True,
    }


async def set_setting(bot, guild_id: int, field: str, enabled: bool) -> dict:
    """Whitelisted config writes; no XP module change or implicit enable."""
    if field not in {"enabled", "track_moves", "track_duration"}:
        raise ValueError("Unknown voice tracking option")
    await ensure_schema(bot)
    await bot.db.execute(
        "INSERT INTO member_voice_history_settings (guild_id, " + field + ") "
        "VALUES (?,?) ON CONFLICT(guild_id) DO UPDATE SET "
        + field + "=excluded." + field,
        (int(guild_id), int(bool(enabled))),
    )
    if field == "enabled" and not enabled:
        # Do not accumulate an offline interval if an admin pauses monitoring.
        await bot.db.execute(
            "DELETE FROM member_voice_history_sessions WHERE guild_id=?",
            (int(guild_id),),
        )
    return await get_settings(bot, guild_id)


async def get_member_summary(bot, guild_id: int, user_id: int) -> dict:
    settings = await get_settings(bot, guild_id)
    row = await bot.db.fetchone(
        "SELECT seconds,completed_sessions FROM member_voice_history_totals "
        "WHERE guild_id=? AND user_id=?", (int(guild_id), int(user_id)),
    )
    session = await bot.db.fetchone(
        "SELECT channel_id,started_at,channel_started_at "
        "FROM member_voice_history_sessions WHERE guild_id=? AND user_id=?",
        (int(guild_id), int(user_id)),
    )
    return {
        **settings,
        "seconds": int(row["seconds"] or 0) if row else 0,
        "completed_sessions": int(row["completed_sessions"] or 0) if row else 0,
        "session": dict(session) if session else None,
    }


def duration_label(seconds: int | None) -> str:
    if seconds is None:
        return "Inconnue"
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, sec = divmod(rem, 60)
    if hours:
        return f"{hours} h {minutes} min"
    if minutes:
        return f"{minutes} min {sec} s"
    return f"{sec} s"


async def record_transition(
    bot, guild_id: int, user_id: int,
    before_id: int | None, after_id: int | None,
    *, now: int | None = None,
) -> VoiceTransition | None:
    """Apply a real channel transition, returning metadata for the log.

    Mic/deafen state changes are not counted as connect/disconnect. For an
    unmatched session (e.g. gateway missed a transition) do not invent
    elapsed time. A new baseline starts at the observed event.
    """
    if before_id == after_id:
        return None
    settings = await get_settings(bot, guild_id)
    if not settings["enabled"]:
        return None
    stamp = int(now if now is not None else time.time())
    guild_id, user_id = int(guild_id), int(user_id)
    row = await bot.db.fetchone(
        "SELECT channel_id,started_at,channel_started_at FROM member_voice_history_sessions "
        "WHERE guild_id=? AND user_id=?", (guild_id, user_id),
    )
    matches_before = bool(row and before_id is not None and int(row["channel_id"]) == before_id)

    if after_id is None:  # Leave
        await bot.db.execute(
            "DELETE FROM member_voice_history_sessions WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        elapsed = max(0, stamp - int(row["started_at"])) if matches_before else None
        segment = max(0, stamp - int(row["channel_started_at"])) if matches_before else None
        if elapsed is not None and settings["track_duration"]:
            await bot.db.execute(
                "INSERT INTO member_voice_history_totals "
                "(guild_id,user_id,seconds,completed_sessions) VALUES (?,?,?,1) "
                "ON CONFLICT(guild_id,user_id) DO UPDATE SET "
                "seconds=member_voice_history_totals.seconds+excluded.seconds,"
                "completed_sessions=member_voice_history_totals.completed_sessions+1",
                (guild_id, user_id, elapsed),
            )
        return VoiceTransition("voice_leave", before_id, None,
                               duration_seconds=elapsed if settings["track_duration"] else None,
                               segment_seconds=segment if settings["track_duration"] else None)

    # Join or move (upsert avoids losing sessions on normal reconnect).
    started_at = int(row["started_at"]) if matches_before else stamp
    segment = max(0, stamp - int(row["channel_started_at"])) if matches_before else None
    if before_id is None:
        # A stale prior session may exist after downtime; start from NOW.
        started_at = stamp
        segment = None
    await bot.db.execute(
        "INSERT INTO member_voice_history_sessions "
        "(guild_id,user_id,channel_id,started_at,channel_started_at) "
        "VALUES (?,?,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET "
        "channel_id=excluded.channel_id,started_at=excluded.started_at,"
        "channel_started_at=excluded.channel_started_at",
        (guild_id, user_id, int(after_id), started_at, stamp),
    )
    if before_id is None:
        return VoiceTransition("voice_join", None, after_id)
    return VoiceTransition(
        "voice_move", before_id, after_id,
        segment_seconds=segment if settings["track_duration"] else None,
        archive=bool(settings["track_moves"]),
    )


async def archive_undelivered_event(
    guild_id: int, kind: str, embed: discord.Embed,
) -> None:
    """Keep the staff history complete even without a configured log channel."""
    from utils.wide_logs import _record_log
    await _record_log(guild_id=guild_id, log_type=kind, kind="voice", embed=embed)


async def reconcile_guild(bot, guild: discord.Guild, *, now: int | None = None) -> None:
    """Observe active voice members after gateway ready, without fake duration.

    If the member was already in the same salon, preserve the persisted
    start time; if they moved or left while bot was offline, start a new
    baseline or delete the stale session. No synthetic join/leave logs.
    """
    if not (await get_settings(bot, guild.id))["enabled"]:
        return
    stamp = int(now if now is not None else time.time())
    try:
        active = {
            member.id: channel.id
            for channel in guild.voice_channels
            for member in channel.members
            if not member.bot
        }
        stored = await bot.db.fetchall(
            "SELECT user_id,channel_id FROM member_voice_history_sessions WHERE guild_id=?",
            (guild.id,),
        )
        known = {int(row["user_id"]): int(row["channel_id"]) for row in stored}
        for user_id, old_channel in known.items():
            if user_id not in active:
                await bot.db.execute(
                    "DELETE FROM member_voice_history_sessions WHERE guild_id=? AND user_id=?",
                    (guild.id, user_id),
                )
        for user_id, channel_id in active.items():
            if known.get(user_id) == channel_id:
                continue
            await bot.db.execute(
                "INSERT INTO member_voice_history_sessions "
                "(guild_id,user_id,channel_id,started_at,channel_started_at) "
                "VALUES (?,?,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET "
                "channel_id=excluded.channel_id,started_at=excluded.started_at,"
                "channel_started_at=excluded.channel_started_at",
                (guild.id, user_id, channel_id, stamp, stamp),
            )
    except Exception:
        logger.exception("Voice reconciliation failed for guild %s", guild.id)
        raise
