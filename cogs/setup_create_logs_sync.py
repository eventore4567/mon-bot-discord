"""Répare la liaison entre +setup -> Create Logs et le moteur log_settings.

Le bouton/commande historique crée les 7 salons puis écrit leurs IDs dans guild_config.
Depuis la refonte des logs indépendants, les listeners envoient via log_settings. Si une
ligne log_settings avait déjà été créée avant les salons, elle pouvait rester désactivée
ou sans channel_id : les salons existaient donc visuellement mais ne recevaient rien.

Ce patch garde les deux sources en phase sans casser les désactivations volontaires :
- après un clic explicite sur Create Logs, les 7 salons générés sont liés ET activés ;
- au démarrage, on répare seulement les lignes absentes/incomplètes (ou les routes actives
  devenues invalides), sans réactiver une catégorie que l'admin a volontairement coupée.
"""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from utils import log_service

logger = logging.getLogger("bot.setup-create-logs-sync")
_INSTALLED = False
_BOOTSTRAP_STARTED = False

# Colonnes écrites par Configuration.create_log_channels -> types lus par log_service.
COLUMN_TO_LOG_TYPE = {
    "log_server": "server",
    "log_messages": "messages",
    "log_members": "members",
    "log_voice": "voice",
    "log_roles": "roles",
    "log_moderation": "moderation",
    "log_automod": "automod",
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
    """Synchronise les 7 salons créés par +setup/+create-logs avec log_settings."""
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

        row = await bot.db.fetchone(
            "SELECT enabled, channel_id FROM log_settings WHERE guild_id = ? AND log_type = ?",
            (guild.id, log_type),
        )

        if force_enable:
            # Un clic sur "Create Logs" signifie explicitement : créer/configurer un système
            # de logs fonctionnel. Le salon généré devient donc la route de cette catégorie.
            await log_service.set_log_channel(bot, guild.id, log_type, channel.id)
            await log_service.set_log_enabled(bot, guild.id, log_type, True)
            synced += 1
            continue

        if row is None:
            # Aucune préférence moderne n'existe encore : reprendre le salon généré.
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
            # Cas exact du bug : ligne déjà créée, mais aucun salon relié. On la répare et
            # on l'active puisque l'ancien système possède bien un salon Create Logs.
            await log_service.set_log_channel(bot, guild.id, log_type, channel.id)
            await log_service.set_log_enabled(bot, guild.id, log_type, True)
            synced += 1
        elif bool(row["enabled"]) and not isinstance(current_channel, discord.TextChannel):
            # Route active cassée (salon supprimé/recréé) : utiliser le salon historique.
            await log_service.set_log_channel(bot, guild.id, log_type, channel.id)
            synced += 1
        # Si enabled=0 ET qu'un channel_id valide existe, ne rien toucher : OFF volontaire.

    # Compatibilité avec les anciens modules qui cherchent encore un salon général.
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
    await bot.wait_until_ready()
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
    global _INSTALLED, _BOOTSTRAP_STARTED
    if _INSTALLED:
        return

    from . import configuration

    original = configuration.Configuration.create_log_channels
    if not getattr(original, "_sentrix_log_settings_sync", False):
        async def create_log_channels_synced(self, guild, author):
            created = await original(self, guild, author)
            # Important : exécuté même si `created == []`. Ainsi un serveur où les 7 salons
            # existent déjà mais sont déliés de log_settings est réparé immédiatement.
            await sync_setup_created_logs(self.bot, guild, force_enable=True)
            return created

        create_log_channels_synced._sentrix_log_settings_sync = True
        configuration.Configuration.create_log_channels = create_log_channels_synced

    if not _BOOTSTRAP_STARTED:
        asyncio.create_task(_bootstrap(bot), name="sentrix-setup-create-logs-sync")
        _BOOTSTRAP_STARTED = True

    _INSTALLED = True
    logger.info("Synchronisation +setup -> Create Logs avec log_settings activée.")
