"""Rend le choix initial de langue accessible à tous les membres du serveur.

Le panneau envoyé quand le bot rejoint un serveur utilisait historiquement une vue qui
réservait les boutons Français / English aux administrateurs. Ce correctif ne touche pas
aux permissions de +setup : il rend uniquement ce panneau initial utilisable par n'importe
quel membre présent sur le serveur.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger("bot.public-language-choice")
_INSTALLED = False


def install(bot: commands.Bot) -> None:
    del bot
    global _INSTALLED
    if _INSTALLED:
        return

    from . import language_runtime
    from utils import embeds

    view_cls = language_runtime.LanguageChoiceView
    if getattr(view_cls, "_sentrix_public_choice", False):
        _INSTALLED = True
        return

    def public_init(self, bot_obj: commands.Bot):
        discord.ui.View.__init__(self, timeout=None)
        self.bot = bot_obj

        fr = discord.ui.Button(
            label="Francais",
            emoji="🇫🇷",
            style=discord.ButtonStyle.primary,
            custom_id="sentrix:language:fr",
        )
        en = discord.ui.Button(
            label="English",
            emoji="🇬🇧",
            style=discord.ButtonStyle.secondary,
            custom_id="sentrix:language:en",
        )

        async def choose(interaction: discord.Interaction, language: str):
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return

            await language_runtime.set_language(self.bot, interaction.guild.id, language)
            if language == language_runtime.LANG_EN:
                embed = embeds.success(
                    "English is now the server language. Command names in `+help` and the setup interface are displayed in English.",
                    title="🇬🇧 Language selected",
                )
            else:
                embed = embeds.success(
                    "Le francais est maintenant la langue du serveur. Les noms dans `+help` et l'interface de configuration sont affiches en francais.",
                    title="🇫🇷 Langue selectionnee",
                )
            await interaction.response.edit_message(embed=embed, view=None)

        async def fr_callback(interaction: discord.Interaction):
            await choose(interaction, language_runtime.LANG_FR)

        async def en_callback(interaction: discord.Interaction):
            await choose(interaction, language_runtime.LANG_EN)

        fr.callback = fr_callback
        en.callback = en_callback
        self.add_item(fr)
        self.add_item(en)

    view_cls.__init__ = public_init
    view_cls._sentrix_public_choice = True
    _INSTALLED = True
    logger.info("Choix initial de langue accessible à tous les membres.")
