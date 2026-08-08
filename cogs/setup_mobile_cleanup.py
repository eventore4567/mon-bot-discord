"""Supprime réellement la colonne Modules/✅/⚠️ de l'accueil +setup.

Le premier correctif enveloppait ``_build_home_embed``. Or la couche premium appelle sa
fonction de rendu d'accueil directement depuis ``SetupView.build_embed`` ; le wrapper ne
voyait donc jamais l'embed final. Ce correctif enveloppe ``build_embed`` lui-même afin de
nettoyer le message réellement envoyé à Discord, même si d'autres couches UX l'enveloppent
ensuite.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger("bot.setup-mobile-cleanup")
_INSTALLED = False


def _clean_home_embed(embed: discord.Embed) -> discord.Embed:
    """Retire le bloc étroit qui empilait les icônes sur mobile."""
    for index in range(len(embed.fields) - 1, -1, -1):
        field = embed.fields[index]
        name = str(field.name or "").strip()
        if "Modules" in name:
            embed.remove_field(index)

    # Le guide ne doit jamais partager une ligne avec un autre champ : sur mobile cela
    # recréait une colonne minuscule. On le force en pleine largeur.
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


def install(bot: commands.Bot) -> None:
    del bot
    global _INSTALLED
    if _INSTALLED:
        return

    from . import configuration

    # IMPORTANT : patcher build_embed, pas _build_home_embed. La couche premium de setup
    # appelle sa fonction locale build_home_embed directement ; l'ancien wrapper ne pouvait
    # donc pas supprimer le champ Modules sur le message final.
    original_build_embed = configuration.SetupView.build_embed

    async def build_embed_without_mobile_status_column(self) -> discord.Embed:
        embed = await original_build_embed(self)
        if getattr(self, "page", None) == -1:
            _clean_home_embed(embed)
        return embed

    configuration.SetupView.build_embed = build_embed_without_mobile_status_column
    _INSTALLED = True
    logger.info("Accueil +setup nettoyé sur l'embed final : colonne Modules/✅/⚠️ supprimée.")
