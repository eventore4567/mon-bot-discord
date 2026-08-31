"""Répare la liaison entre +setup -> Create Logs et le moteur de logs par catégorie.

Le bouton/commande historique crée 7 salons puis écrit leurs IDs dans guild_config.
La nouvelle architecture route désormais les événements vers des catégories. Ce module
maintient la compatibilité avec les salons historiques sans confondre l'ancienne clé
``server`` (qui signifiait Salons) avec la nouvelle catégorie Serveur.
"""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from utils import log_service

logger = logging.getLogger("bot.setup-create-logs-sync")

# Colonnes écrites par Configuration.create_log_channels -> catégories modernes.
# Important : ``log_server`` désigne historiquement les événements de SALONS.
COLUMN_TO_LOG_TYPE = {
    "log_server": "channels",
    "log_messages": "messages",
    "log_members": "members",
    "log_voice": "voice",
    "log_roles": "roles",
    "log_moderation": "moderation",
    "log_automod": "protection",
}


def _configured_channel(guild: discord.Guild, conf, column: str) -> discord.TextChannel | None:
    if not conf:
        return None
    try:
        channel_id = conf[column]
    except (KeyError, IndexError, TypeError):
        return None
    if not channel_id:
        return None
    try:
        channel = guild.get_channel(int(channel_id))
    except (TypeError, ValueError):
        return None
    return channel if isinstance(channel, discord.TextChannel) else None


async def sync_setup_created_logs(
    bot: commands.Bot,
    guild: discord.Guild,
    *,
    force_enable: bool,
) -> int:
    """Synchronise les 7 salons historiques avec les catégories de logs actuelles."""
    conf = await bot.db.get_guild_config(guild.id)
    if not conf:
        return 0

    synced = 0
    moderation_channel_id: int | None = None

    for column, log_type in COLUMN_TO_LOG_TYPE.items():
        channel = _configured_channel(guild, conf, column)
        if channel is None:
            continue

        if log_type == "moderation":
            moderation_channel_id = channel.id

        # On lit l'ancien miroir uniquement pour décider si une préférence existait.
        legacy_keys = {
            "channels": ("server", "channels"),
            "protection": ("automod", "protection"),
        }.get(log_type, (log_type,))
        placeholders = ",".join("?" for _ in legacy_keys)
        row = await bot.db.fetchone(
            f"SELECT enabled, channel_id FROM log_settings WHERE guild_id = ? AND log_type IN ({placeholders}) "
            "ORDER BY CASE WHEN channel_id IS NOT NULL THEN 0 ELSE 1 END LIMIT 1",
            (guild.id, *legacy_keys),
        )

        if force_enable:
            # Un clic sur Create Logs signifie explicitement que les salons générés doivent
            # devenir les routes actives de leurs catégories correspondantes.
            await log_service.set_log_channel(bot, guild.id, log_type, channel.id)
            await log_service.set_log_enabled(bot, guild.id, log_type, True)
            synced += 1
            continue

        if row is None:
            await log_service.get_log_setting(bot, guild.id, log_type)
            await log_service.set_log_channel(bot, guild.id, log_type, channel.id)
            await log_service.set_log_enabled(bot, guild.id, log_type, True)
            synced += 1
            continue

        current_id = row["channel_id"]
        current_channel = None
        if current_id:
            try:
                current_channel = guild.get_channel(int(current_id))
            except (TypeError, ValueError):
                current_channel = None

        if not current_id:
            await log_service.set_log_channel(bot, guild.id, log_type, channel.id)
            await log_service.set_log_enabled(bot, guild.id, log_type, True)
            synced += 1
        elif bool(row["enabled"]) and not isinstance(current_channel, discord.TextChannel):
            await log_service.set_log_channel(bot, guild.id, log_type, channel.id)
            synced += 1
        # enabled=0 + salon valide = désactivation volontaire, on ne réactive pas.

    # Compatibilité : le salon de modération reste aussi le repli général si aucun salon
    # général valide n'existe encore. La catégorie Serveur peut donc fonctionner sans
    # inventer un huitième salon lors d'une migration historique.
    if moderation_channel_id:
        try:
            current_general = conf["log_channel"]
        except (KeyError, IndexError, TypeError):
            current_general = None
        if not current_general or guild.get_channel(int(current_general)) is None:
            await bot.db.set_guild_config(guild.id, "log_channel", moderation_channel_id)

    if synced:
        logger.info(
            "Create Logs synchronisé sur %s (%s) : %s route(s) réparée(s).",
            guild.name,
            guild.id,
            synced,
        )
    return synced


async def _bootstrap(bot: commands.Bot) -> None:
    try:
        await bot.wait_until_ready()
    except RuntimeError:
        # En CI le client Discord n'est jamais authentifié : rien à réparer côté guildes.
        return
    await asyncio.sleep(3)
    for guild in list(bot.guilds):
        try:
            await sync_setup_created_logs(bot, guild, force_enable=False)
        except Exception:
            logger.exception(
                "Réparation Create Logs impossible sur %s (%s).",
                guild.name,
                guild.id,
            )


def install(bot: commands.Bot) -> None:
    """Patche Configuration une fois, puis lance un bootstrap par instance de bot."""
    from . import configuration

    original = configuration.Configuration.create_log_channels
    if not getattr(original, "_sentrix_log_settings_sync", False):
        async def create_log_channels_synced(self, guild, author):
            created = await original(self, guild, author)
            await sync_setup_created_logs(self.bot, guild, force_enable=True)
            return created

        create_log_channels_synced._sentrix_log_settings_sync = True
        configuration.Configuration.create_log_channels = create_log_channels_synced

    if getattr(bot, "_sentrix_setup_create_logs_sync_installed", False):
        return
    bot._sentrix_setup_create_logs_sync_installed = True
    asyncio.create_task(_bootstrap(bot), name="sentrix-setup-create-logs-sync")
    logger.info("Synchronisation +setup -> Create Logs avec les catégories de logs activée.")
