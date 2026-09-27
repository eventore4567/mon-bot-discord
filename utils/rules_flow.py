"""Shared rules -> verification flow for SentriX.

The rules panel and the reinforced verification portal are separate systems, but they
can be chained. A member accepts the current rules version first; reinforced verification
then checks that acceptance before starting or completing the challenge.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

_RULES_SCHEMA = """
CREATE TABLE IF NOT EXISTS rules_acceptances (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    rules_version TEXT NOT NULL,
    accepted_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
)
"""


async def ensure_schema(bot) -> None:
    await bot.db.execute(_RULES_SCHEMA)


def _row_value(row: Any, key: str, default=None):
    if row is None:
        return default
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


async def current_rules_record(bot, guild_id: int) -> dict | None:
    """Return the currently published rules record, if any."""
    try:
        row = await bot.db.fetchone(
            "SELECT rules_text,image_url,message_id,updated_at "
            "FROM dashboard_verification_panels WHERE guild_id=?",
            (guild_id,),
        )
    except Exception:
        return None
    if not row or not _row_value(row, "message_id") or not str(_row_value(row, "rules_text", "")).strip():
        return None
    return {
        "rules_text": str(_row_value(row, "rules_text", "")),
        "image_url": str(_row_value(row, "image_url", "") or ""),
        "message_id": int(_row_value(row, "message_id", 0) or 0),
        "updated_at": int(_row_value(row, "updated_at", 0) or 0),
    }


async def current_rules_version(bot, guild_id: int) -> str | None:
    record = await current_rules_record(bot, guild_id)
    if not record:
        return None
    payload = (
        f"{record['updated_at']}\n{record['message_id']}\n"
        f"{record['rules_text']}\n{record['image_url']}"
    ).encode("utf-8", errors="ignore")
    return hashlib.sha256(payload).hexdigest()


async def accept_current_rules(bot, guild_id: int, user_id: int) -> str | None:
    """Record acceptance of the exact currently-published rules version."""
    version = await current_rules_version(bot, guild_id)
    if version is None:
        return None
    await ensure_schema(bot)
    await bot.db.execute(
        "INSERT INTO rules_acceptances(guild_id,user_id,rules_version,accepted_at) "
        "VALUES(?,?,?,?) "
        "ON CONFLICT(guild_id,user_id) DO UPDATE SET "
        "rules_version=excluded.rules_version, accepted_at=excluded.accepted_at",
        (guild_id, user_id, version, int(time.time())),
    )
    return version


async def has_accepted_current_rules(bot, guild_id: int, user_id: int) -> bool:
    version = await current_rules_version(bot, guild_id)
    if version is None:
        return True
    await ensure_schema(bot)
    row = await bot.db.fetchone(
        "SELECT rules_version FROM rules_acceptances WHERE guild_id=? AND user_id=?",
        (guild_id, user_id),
    )
    return bool(row and str(_row_value(row, "rules_version", "")) == version)


async def rules_channel_id(bot, guild_id: int) -> int | None:
    try:
        conf = await bot.db.get_guild_config(guild_id)
    except Exception:
        return None
    raw = _row_value(conf, "verification_channel")
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


async def acceptance_status(bot, guild_id: int, user_id: int) -> dict:
    version = await current_rules_version(bot, guild_id)
    return {
        "rules_published": version is not None,
        "accepted_current": await has_accepted_current_rules(bot, guild_id, user_id),
        "channel_id": await rules_channel_id(bot, guild_id),
    }


__all__ = [
    "ensure_schema",
    "current_rules_record",
    "current_rules_version",
    "accept_current_rules",
    "has_accepted_current_rules",
    "rules_channel_id",
    "acceptance_status",
]
