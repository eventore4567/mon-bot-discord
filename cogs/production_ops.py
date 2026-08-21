"""SentriX production operations: backups, health alerts and recovery metadata.

This module intentionally exposes no Discord command. It is installed by the common
runtime loader and only uses technical metadata already kept by runtime_observability_v26.

Goals:
- create verified SQLite backups without stopping the bot;
- keep a bounded retention set next to the database (or SENTRIX_BACKUP_DIR);
- alert the configured ops channel/user when repeated technical failures appear;
- never include message contents, SQL parameters, tokens or AI prompts in alerts.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import discord
from discord.ext import commands

from database.db import PRIMARY_CREATOR_ID

logger = logging.getLogger("bot.production-ops")

_TECHNICAL_ERROR_IGNORE = {
    "CommandNotFound",
    "BadArgument",
    "MissingRequiredArgument",
    "TooManyArguments",
    "MemberNotFound",
    "UserNotFound",
    "RoleNotFound",
    "ChannelNotFound",
    "CommandOnCooldown",
    "MissingPermissions",
    "BotMissingPermissions",
    "NoPrivateMessage",
    "CheckFailure",
}


def _positive_int_env(name: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    try:
        value = int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _ops_state(bot: commands.Bot) -> dict[str, Any]:
    current = getattr(bot, "_sentrix_production_ops", None)
    if isinstance(current, dict):
        return current
    current = {
        "installed": False,
        "backup_dir": None,
        "last_backup_at": None,
        "last_backup_path": None,
        "last_backup_ok": None,
        "last_backup_error": None,
        "last_alert_at": None,
        "last_alert_key": None,
        "last_alert_error": None,
    }
    bot._sentrix_production_ops = current
    return current


def _database_path(bot: commands.Bot) -> Path | None:
    db = getattr(bot, "db", None)
    raw = getattr(db, "path", None)
    if not raw:
        return None
    return Path(str(raw)).expanduser().resolve()


def _backup_dir(bot: commands.Bot) -> Path | None:
    db_path = _database_path(bot)
    if db_path is None:
        return None
    configured = (os.getenv("SENTRIX_BACKUP_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    # If DATABASE_PATH points into a Railway volume, backups inherit the same persistent
    # volume automatically instead of being written into the ephemeral repository tree.
    return db_path.parent / "backups"


def _sqlite_integrity(path: Path) -> tuple[bool, str]:
    try:
        with sqlite3.connect(str(path), timeout=10) as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        result = str(row[0] if row else "unknown")
        return result.casefold() == "ok", result[:300]
    except Exception as exc:
        return False, type(exc).__name__


def _create_sqlite_backup_sync(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".tmp")
    temp.unlink(missing_ok=True)
    try:
        with sqlite3.connect(str(source), timeout=20) as src, sqlite3.connect(str(temp), timeout=20) as dst:
            src.backup(dst, pages=256, sleep=0.01)
            dst.execute("PRAGMA wal_checkpoint(PASSIVE)")
            dst.commit()
        ok, detail = _sqlite_integrity(temp)
        if not ok:
            raise RuntimeError(f"backup integrity_check failed: {detail}")
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)


def _prune_backups_sync(directory: Path, keep: int) -> None:
    backups = sorted(directory.glob("sentrix-*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in backups[keep:]:
        try:
            stale.unlink()
        except OSError:
            logger.warning("Impossible de supprimer l'ancien backup %s", stale, exc_info=True)


async def create_verified_backup(bot: commands.Bot) -> Path | None:
    """Create one consistent backup and verify it before publishing the file."""
    state = _ops_state(bot)
    source = _database_path(bot)
    directory = _backup_dir(bot)
    if source is None or directory is None or not source.exists():
        state["last_backup_ok"] = False
        state["last_backup_error"] = "database_path_unavailable"
        return None

    # PostgreSQL needs provider-level backups. This bot still keeps SQLite as its local
    # canonical fallback; this function deliberately backs up only the SQLite file.
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    destination = directory / f"sentrix-{timestamp}.sqlite3"
    try:
        await asyncio.to_thread(_create_sqlite_backup_sync, source, destination)
        keep = _positive_int_env("SENTRIX_BACKUP_RETENTION", 14, minimum=2, maximum=200)
        await asyncio.to_thread(_prune_backups_sync, directory, keep)
    except Exception as exc:
        state["last_backup_at"] = int(time.time())
        state["last_backup_ok"] = False
        state["last_backup_error"] = type(exc).__name__
        logger.exception("Backup SQLite SentriX échoué.")
        return None

    state["backup_dir"] = str(directory)
    state["last_backup_at"] = int(time.time())
    state["last_backup_path"] = str(destination)
    state["last_backup_ok"] = True
    state["last_backup_error"] = None
    logger.info("Backup SQLite vérifié créé : %s", destination)
    return destination


def _recent_technical_errors(bot: commands.Bot, *, window_seconds: int = 300) -> list[dict[str, Any]]:
    state = getattr(bot, "_sentrix_observability_v26", None)
    if not isinstance(state, dict):
        return []
    cutoff = int(time.time()) - max(30, int(window_seconds))
    result = []
    for item in list(state.get("errors") or []):
        if not isinstance(item, dict):
            continue
        if int(item.get("at") or 0) < cutoff:
            continue
        if str(item.get("type") or "") in _TECHNICAL_ERROR_IGNORE:
            continue
        result.append(item)
    return result


def _health_alert(bot: commands.Bot) -> tuple[str | None, str | None]:
    state = getattr(bot, "_sentrix_observability_v26", None)
    if not isinstance(state, dict):
        return None, None

    errors = _recent_technical_errors(bot)
    threshold = _positive_int_env("SENTRIX_ALERT_ERROR_THRESHOLD", 5, minimum=2, maximum=100)
    if len(errors) >= threshold:
        kinds: dict[str, int] = {}
        for item in errors:
            name = str(item.get("type") or "Erreur")[:80]
            kinds[name] = kinds.get(name, 0) + 1
        top = sorted(kinds.items(), key=lambda pair: (-pair[1], pair[0]))[:4]
        detail = ", ".join(f"{name} ×{count}" for name, count in top)
        return f"errors:{detail}", f"{len(errors)} erreurs techniques en 5 min ({detail})."

    slow_commands = list(state.get("slow_commands") or [])
    if slow_commands:
        latest = slow_commands[-1]
        ms = float(latest.get("ms") or 0)
        if ms >= float(_positive_int_env("SENTRIX_ALERT_SLOW_COMMAND_MS", 6000, minimum=2000, maximum=120000)):
            command = str(latest.get("command") or "inconnue")[:100]
            return f"slow-command:{command}", f"Commande lente détectée : `{command}` ({ms:.0f} ms)."

    slow_db = list(state.get("slow_db") or [])
    if slow_db:
        latest = slow_db[-1]
        ms = float(latest.get("ms") or 0)
        if ms >= float(_positive_int_env("SENTRIX_ALERT_SLOW_DB_MS", 1500, minimum=500, maximum=120000)):
            method = str(latest.get("method") or "DB")[:40]
            return f"slow-db:{method}", f"Base de données lente : `{method}` ({ms:.0f} ms)."

    ops = _ops_state(bot)
    if ops.get("last_backup_ok") is False:
        return "backup-failed", f"Le dernier backup SQLite a échoué ({ops.get('last_backup_error') or 'erreur inconnue'})."
    return None, None


async def _resolve_alert_target(bot: commands.Bot):
    raw_channel = (os.getenv("SENTRIX_OPS_ALERT_CHANNEL_ID") or "").strip()
    if raw_channel.isdigit():
        channel_id = int(raw_channel)
        channel = bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                channel = None
        if channel is not None and hasattr(channel, "send"):
            return channel

    raw_user = (os.getenv("SENTRIX_OPS_ALERT_USER_ID") or "").strip()
    user_id = int(raw_user) if raw_user.isdigit() else PRIMARY_CREATOR_ID
    user = bot.get_user(user_id)
    if user is None:
        try:
            user = await bot.fetch_user(user_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None
    return user


async def _send_ops_alert(bot: commands.Bot, key: str, detail: str) -> None:
    state = _ops_state(bot)
    now_value = int(time.time())
    cooldown = _positive_int_env("SENTRIX_ALERT_COOLDOWN_SECONDS", 900, minimum=60, maximum=86400)
    if state.get("last_alert_key") == key and now_value - int(state.get("last_alert_at") or 0) < cooldown:
        return

    target = await _resolve_alert_target(bot)
    if target is None:
        state["last_alert_error"] = "target_unavailable"
        logger.error("Alerte SentriX non envoyée (cible indisponible) : %s", detail)
        return

    release = "inconnu"
    obs = getattr(bot, "_sentrix_observability_v26", None)
    if isinstance(obs, dict):
        release = str(obs.get("release") or "inconnu")[:20]
    text = (
        "⚠️ **SentriX — alerte production**\n"
        f"{detail}\n"
        f"Release : `{release}`\n"
        "Aucun contenu de message, token ou paramètre SQL n'est inclus dans cette alerte."
    )
    try:
        await target.send(text, allowed_mentions=discord.AllowedMentions.none())
    except (discord.Forbidden, discord.HTTPException) as exc:
        state["last_alert_error"] = type(exc).__name__
        logger.exception("Impossible d'envoyer l'alerte production SentriX.")
        return

    state["last_alert_at"] = now_value
    state["last_alert_key"] = key
    state["last_alert_error"] = None


async def _backup_loop(bot: commands.Bot) -> None:
    await bot.wait_until_ready()
    # Give migrations/startup tasks a short window before taking the first snapshot.
    await asyncio.sleep(20)
    while not bot.is_closed():
        await create_verified_backup(bot)
        interval = _positive_int_env(
            "SENTRIX_BACKUP_INTERVAL_SECONDS", 6 * 3600, minimum=900, maximum=7 * 86400
        )
        await asyncio.sleep(interval)


async def _alert_loop(bot: commands.Bot) -> None:
    await bot.wait_until_ready()
    await asyncio.sleep(60)
    while not bot.is_closed():
        key, detail = _health_alert(bot)
        if key and detail:
            await _send_ops_alert(bot, key, detail)
        await asyncio.sleep(60)


def snapshot(bot: commands.Bot) -> dict[str, Any]:
    state = dict(_ops_state(bot))
    directory = _backup_dir(bot)
    if directory and directory.exists():
        try:
            state["backup_count"] = len(list(directory.glob("sentrix-*.sqlite3")))
        except OSError:
            state["backup_count"] = None
    else:
        state["backup_count"] = 0
    return state


def install(bot: commands.Bot) -> None:
    state = _ops_state(bot)
    if state.get("installed"):
        return
    state["installed"] = True
    state["backup_dir"] = str(_backup_dir(bot) or "") or None

    # CI constructs a Bot object without logging into Discord; avoid creating tasks there.
    if not getattr(getattr(bot, "http", None), "token", None):
        logger.info("Production ops chargé en mode audit (aucune tâche réseau démarrée).")
        return

    bot._sentrix_backup_task = asyncio.create_task(_backup_loop(bot))
    bot._sentrix_ops_alert_task = asyncio.create_task(_alert_loop(bot))
    logger.info("Production ops actif : backups vérifiés + alertes techniques, 0 nouvelle commande.")


async def setup(bot: commands.Bot) -> None:
    install(bot)
