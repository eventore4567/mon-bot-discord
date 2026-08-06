"""Ajoute un ping @everyone au règlement publié par +create-server."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands


logger = logging.getLogger("bot.server_builder.everyone")
RULES_MARKER = "SentriX • Règlement automatique v2"
_INSTALLED = False


async def install_server_builder_everyone_ping(bot: commands.Bot) -> None:
    """Modifie uniquement la publication du règlement, sans toucher aux autres embeds."""
    global _INSTALLED
    if _INSTALLED:
        return

    from . import server_builder as server_builder_module

    builder_class = server_builder_module.ServerBuilder
    if getattr(builder_class, "_sentrix_everyone_rules_patch", False):
        _INSTALLED = True
        return

    original_publish_once = builder_class._publish_once

    async def publish_once_with_everyone(
        channel: discord.TextChannel | None,
        marker: str,
        embed: discord.Embed,
    ) -> bool:
        if marker != RULES_MARKER:
            return await original_publish_once(channel, marker, embed)
        if channel is None:
            return False

        try:
            async for message in channel.history(limit=50):
                if message.author.id != channel.guild.me.id or not message.embeds:
                    continue
                footer = message.embeds[0].footer.text
                if footer == marker:
                    # Le @everyone reste visible, mais une nouvelle exécution de
                    # +create-server ne renvoie pas un deuxième ping inutile.
                    await message.edit(content="@everyone", embed=embed)
                    return False
        except discord.HTTPException:
            logger.warning(
                "Impossible de parcourir l'historique du salon règlement %s.",
                channel.id,
            )

        await channel.send(
            content="@everyone",
            embed=embed,
            allowed_mentions=discord.AllowedMentions(
                everyone=True,
                users=False,
                roles=False,
                replied_user=False,
            ),
        )
        return True

    builder_class._publish_once = staticmethod(publish_once_with_everyone)
    builder_class._sentrix_everyone_rules_patch = True
    _INSTALLED = True
    logger.info("Ping @everyone du règlement de +create-server activé.")
