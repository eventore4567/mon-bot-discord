"""Synchronise les salons LOGS créés par +create-server avec le moteur log_settings.

Le constructeur historique écrit encore les colonnes guild_config. Le service de logs
moderne utilise log_settings comme source de vérité. Cette couche maintient les deux en
phase pour les structures SentriX existantes et pour les prochains +create-server.
"""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from utils import log_service

logger = logging.getLogger("bot.generated-logs-sync")
_INSTALLED = False

LOG_CHANNELS = {
    "messages": "logs-messages",
    "members": "logs-membres",
    "voice": "logs-vocaux",
    "roles": "logs-rôles",
    "server": "logs-serveur",
    "moderation": "logs-modération",
    "tickets": "logs-tickets",
    "automod": "logs-sécurité",
}


def _plain(value: str) -> str:
    value = (value or "").strip()
    if "・" in value:
        value = value.split("・", 1)[1]
    return value.strip().casefold()


def _find_log_channel(guild: discord.Guild, base_name: str) -> discord.TextChannel | None:
    wanted = base_name.casefold()
    # Priorité à la catégorie LOGS générée par SentriX.
    for channel in guild.text_channels:
        if _plain(channel.name) != wanted:
            continue
        if channel.category and _plain(channel.category.name) == "logs":
            return channel
    for channel in guild.text_channels:
        if _plain(channel.name) == wanted:
            return channel
    return None


async def sync_generated_logs(bot: commands.Bot, guild: discord.Guild) -> int:
    """Active et relie tous les salons logs-* réellement présents dans la guilde."""
    found: dict[str, discord.TextChannel] = {}
    for log_type, base_name in LOG_CHANNELS.items():
        channel = _find_log_channel(guild, base_name)
        if channel is not None:
            found[log_type] = channel

    # Ne touche pas à un serveur quelconque : il faut reconnaître une vraie structure
    # SentriX avec plusieurs salons de logs dédiés.
    if len(found) < 3:
        return 0

    synced = 0
    for log_type, channel in found.items():
        meta = log_service.LOG_TYPES.get(log_type, {})
        legacy_column = meta.get("legacy_column")
        if legacy_column:
            await bot.db.set_guild_config(guild.id, legacy_column, channel.id)

        await log_service.set_log_channel(bot, guild.id, log_type, channel.id)
        await log_service.set_log_enabled(bot, guild.id, log_type, True)
        synced += 1

    # Compatibilité avec les anciens modules qui utilisent encore log_channel comme
    # salon de repli général.
    moderation = found.get("moderation")
    if moderation is not None:
        await bot.db.set_guild_config(guild.id, "log_channel", moderation.id)

    logger.info("Logs SentriX synchronisés sur %s (%s) : %s catégorie(s).", guild.name, guild.id, synced)
    return synced


async def _bootstrap(bot: commands.Bot) -> None:
    await bot.wait_until_ready()
    await asyncio.sleep(4)
    for guild in list(bot.guilds):
        try:
            await sync_generated_logs(bot, guild)
        except Exception:
            logger.exception("Synchronisation des logs impossible sur %s (%s).", guild.name, guild.id)


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import server_builder

    original = server_builder.ServerBuilder._configure_bot_channels
    if not getattr(original, "_sentrix_log_settings_sync", False):
        async def configure_with_log_sync(self, guild, role_map, category_map, channel_map, staff_role_name):
            result = await original(self, guild, role_map, category_map, channel_map, staff_role_name)
            await sync_generated_logs(bot, guild)
            return result

        configure_with_log_sync._sentrix_log_settings_sync = True
        server_builder.ServerBuilder._configure_bot_channels = configure_with_log_sync

    asyncio.create_task(_bootstrap(bot), name="sentrix-generated-logs-sync")
    _INSTALLED = True
    logger.info("Synchronisation automatique des salons LOGS SentriX activée.")
