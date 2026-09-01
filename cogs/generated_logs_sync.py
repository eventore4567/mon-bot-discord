"""Réconciliation légère des salons de logs générés par SentriX.

Ce module ne monkey-patch rien. Il reconnaît uniquement les noms de salons créés par les
constructeurs SentriX et remplit une route ``log_config`` encore vide. Une route choisie
par un administrateur n'est jamais remplacée.
"""
from __future__ import annotations

import asyncio
import logging
import re
import unicodedata

import discord
from discord.ext import commands

from utils import log_service

logger = logging.getLogger("bot.generated-logs-sync")

LOG_CHANNEL_ALIASES: dict[str, tuple[str, ...]] = {
    "moderation": ("logs-moderation", "logs-modération", "logs-modo"),
    "messages": ("logs-messages", "logs-message"),
    "members": ("logs-membre", "logs-membres", "logs-member", "logs-members"),
    "channels": ("logs-salons", "logs-channels", "logs-channel"),
    "roles": ("logs-roles", "logs-rôles", "logs-role", "logs-rôle"),
    "voice": ("logs-vocal", "logs-vocaux", "logs-voice"),
    "server": ("logs-serveur", "logs-server"),
    "tickets": ("logs-tickets", "logs-ticket"),
    "automod": ("automod", "logs-automod", "logs-securite", "logs-sécurité", "logs-security"),
    "spam": ("logs-spam", "logs-protect-spam-logs", "protect-spam-logs"),
    "raid": ("logs-raid", "raidprotect-logs", "raid-protect-logs", "anti-raid-logs"),
    "resources": ("logs-resources", "logs-ressources", "logs-dossiers"),
    "files": ("logs-files", "logs-fichiers"),
}


def _plain(value: str) -> str:
    value = (value or "").strip()
    if "・" in value:
        value = value.split("・", 1)[1]
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.casefold().replace("_", " ")
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


_NORMALIZED = {
    category: frozenset(_plain(alias) for alias in aliases)
    for category, aliases in LOG_CHANNEL_ALIASES.items()
}


def _find_log_channel(guild: discord.Guild, category: str) -> discord.TextChannel | None:
    wanted = _NORMALIZED.get(category, frozenset())
    if not wanted:
        return None

    # Préférence aux salons rangés dans une catégorie de logs SentriX.
    for channel in guild.text_channels:
        parent = getattr(channel, "category", None)
        parent_name = _plain(getattr(parent, "name", "")) if parent else ""
        if _plain(channel.name) in wanted and (
            "logs" in parent_name or ("sentrix" in parent_name and "log" in parent_name)
        ):
            return channel
    for channel in guild.text_channels:
        if _plain(channel.name) in wanted:
            return channel
    return None


async def sync_generated_logs(bot: commands.Bot, guild: discord.Guild) -> int:
    """Complète uniquement les routes encore vides et actives."""
    changed = 0
    for category in log_service.LOG_TYPES:
        try:
            config = await log_service.get_log_config(bot, guild.id, category)
        except Exception:
            logger.exception("Lecture log_config impossible guild=%s category=%s", guild.id, category)
            continue

        if config is None or not config.get("enabled") or config.get("channel_id"):
            continue
        channel = _find_log_channel(guild, category)
        if channel is None:
            continue
        try:
            await log_service.set_log_config(
                bot,
                guild.id,
                category,
                channel_id=channel.id,
                enabled=True,
            )
            changed += 1
            logger.warning(
                "Route de log générée restaurée guild=%s category=%s channel=%s",
                guild.id,
                category,
                channel.id,
            )
        except Exception:
            logger.exception(
                "Synchronisation log généré impossible guild=%s category=%s",
                guild.id,
                category,
            )
    return changed


async def _bootstrap(bot: commands.Bot) -> None:
    try:
        await bot.wait_until_ready()
    except RuntimeError:
        return
    await asyncio.sleep(2)
    total = 0
    for guild in list(bot.guilds):
        total += await sync_generated_logs(bot, guild)
    logger.info("Réconciliation logs terminée : %s route(s) complétée(s).", total)


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_generated_logs_reconciler", False):
        return
    bot._sentrix_generated_logs_reconciler = True
    asyncio.create_task(_bootstrap(bot), name="sentrix-generated-logs-reconcile")


__all__ = ["LOG_CHANNEL_ALIASES", "install", "sync_generated_logs"]
