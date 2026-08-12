"""Répare l'accès aux salons de logs pour la personne autorisée qui les configure.

Le problème venait des salons privés : @everyone était refusé et seuls les rôles staff
recevaient un accès explicite. Un propriétaire/créateur du bot autorisé à lancer
+create-logs ou +create-server pouvait donc créer les logs puis voir « Aucun accès » s'il
ne possédait pas encore un rôle staff du serveur.

Cette couche ne donne aucun accès global aux propriétaires du bot. Elle accorde uniquement
l'accès au membre qui vient d'exécuter un flux de configuration déjà protégé par les checks
existants. Relancer +create-logs répare aussi les salons déjà créés.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from .configuration import Configuration, LOG_CHANNEL_DEFINITIONS
from .server_builder import ServerBuilder

logger = logging.getLogger("bot.log-access-fix")


async def _repair_member_log_access(
    bot: commands.Bot,
    guild: discord.Guild,
    member: discord.Member,
) -> int:
    """Garantit lecture/écriture des logs au configurateur autorisé sans toucher aux autres accès."""
    if not isinstance(member, discord.Member) or member.guild.id != guild.id:
        return 0

    conf = await bot.db.get_guild_config(guild.id)
    if not conf:
        return 0

    channel_ids: set[int] = set()
    for column, _name, _description in LOG_CHANNEL_DEFINITIONS:
        try:
            channel_id = int(conf[column] or 0)
        except (KeyError, TypeError, ValueError):
            channel_id = 0
        if channel_id:
            channel_ids.add(channel_id)

    categories: dict[int, discord.CategoryChannel] = {}
    repaired = 0
    reason = f"Accès aux logs pour le configurateur autorisé {member}"

    for channel_id in channel_ids:
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            continue

        overwrite = channel.overwrites_for(member)
        if (
            overwrite.view_channel is not True
            or overwrite.read_message_history is not True
            or overwrite.send_messages is not True
        ):
            overwrite.view_channel = True
            overwrite.read_message_history = True
            overwrite.send_messages = True
            await channel.set_permissions(member, overwrite=overwrite, reason=reason)
            repaired += 1

        if channel.category is not None:
            categories[channel.category.id] = channel.category

    # Discord masque aussi visuellement une catégorie privée lorsque le membre n'a pas
    # d'overwrite explicite. On répare donc la catégorie en plus des salons eux-mêmes.
    for category in categories.values():
        overwrite = category.overwrites_for(member)
        if (
            overwrite.view_channel is not True
            or overwrite.read_message_history is not True
            or overwrite.send_messages is not True
        ):
            overwrite.view_channel = True
            overwrite.read_message_history = True
            overwrite.send_messages = True
            await category.set_permissions(member, overwrite=overwrite, reason=reason)
            repaired += 1

    return repaired


def _patch_configuration() -> None:
    original = Configuration.create_log_channels
    if getattr(original, "_sentrix_author_log_access_fix", False):
        return

    async def create_log_channels_with_author_access(
        self: Configuration,
        guild: discord.Guild,
        author: discord.Member,
    ):
        created = await original(self, guild, author)
        try:
            repaired = await _repair_member_log_access(self.bot, guild, author)
            if repaired:
                logger.info(
                    "Accès logs réparé pour %s sur %s (%s overwrite(s)).",
                    author,
                    guild.id,
                    repaired,
                )
        except discord.HTTPException:
            logger.exception("Impossible de réparer les permissions des salons de logs.")
        return created

    create_log_channels_with_author_access._sentrix_author_log_access_fix = True
    Configuration.create_log_channels = create_log_channels_with_author_access


def _patch_server_builder() -> None:
    original = ServerBuilder.build_server
    if getattr(original, "_sentrix_author_log_access_fix", False):
        return

    async def build_server_with_author_log_access(
        self: ServerBuilder,
        guild: discord.Guild,
        template_key: str,
        author: discord.Member,
    ) -> discord.Embed:
        result = await original(self, guild, template_key, author)
        try:
            repaired = await _repair_member_log_access(self.bot, guild, author)
            if repaired:
                logger.info(
                    "Accès logs create-server réparé pour %s sur %s (%s overwrite(s)).",
                    author,
                    guild.id,
                    repaired,
                )
        except discord.HTTPException:
            logger.exception("Impossible de réparer les permissions logs après create-server.")
        return result

    build_server_with_author_log_access._sentrix_author_log_access_fix = True
    ServerBuilder.build_server = build_server_with_author_log_access


async def setup(bot: commands.Bot) -> None:
    _patch_configuration()
    _patch_server_builder()
    logger.info("Correctif d'accès aux salons de logs activé.")
