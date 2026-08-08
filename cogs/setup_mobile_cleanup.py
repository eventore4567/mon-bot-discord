"""Nettoyage visuel de l'accueil +setup sur mobile.

Le bloc "Modules" était affiché en colonne inline à côté du guide et devenait très étroit
sur certains clients Discord : les ✅ / ⚠️ s'empilaient verticalement sans leur texte.
Cette couche retire uniquement ce bloc redondant et laisse le menu de modules faire la
navigation. Le guide d'utilisation passe en pleine largeur.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger("bot.setup-mobile-cleanup")
_INSTALLED = False


def install(bot: commands.Bot) -> None:
    del bot
    global _INSTALLED
    if _INSTALLED:
        return

    from . import configuration

    original_build_home = configuration.SetupView._build_home_embed

    async def build_home_without_status_column(self) -> discord.Embed:
        embed = await original_build_home(self)

        # Retire le bloc qui produisait la colonne verticale d'emojis sur mobile.
        for index in range(len(embed.fields) - 1, -1, -1):
            field = embed.fields[index]
            name = str(field.name or "").strip()
            if "Modules" in name:
                embed.remove_field(index)

        # Le guide reste utile, mais doit occuper toute la largeur pour être lisible.
        for index, field in enumerate(list(embed.fields)):
            name = str(field.name or "").strip()
            if "Comment l'utiliser" in name:
                embed.set_field_at(
                    index,
                    name=name,
                    value=field.value,
                    inline=False,
                )

        return embed

    configuration.SetupView._build_home_embed = build_home_without_status_column
    _INSTALLED = True
    logger.info("Accueil +setup mobile nettoyé : colonne Modules/✅/⚠️ supprimée.")
