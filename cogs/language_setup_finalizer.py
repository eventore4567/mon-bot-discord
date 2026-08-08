"""Applique la langue sur la version FINALE de +setup.

`language_runtime` peut être importé avant le chargement officiel du cog Configuration.
Les couches setup premium/tickets remplacent ensuite `SetupView.build_embed/render_page`.
Ce finaliseur se réexécute après chaque extension et enveloppe uniquement les méthodes
actuelles si elles ne portent pas déjà son marqueur. Le sélecteur FR/EN survit donc à
toutes les autres couches de rendu.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from . import language_runtime

logger = logging.getLogger("bot.language-setup-finalizer")


def install(bot: commands.Bot) -> None:
    del bot
    try:
        from . import configuration
    except Exception:
        return

    view_cls = getattr(configuration, "SetupView", None)
    if view_cls is None:
        return

    current_build = view_cls.build_embed
    if not getattr(current_build, "_sentrix_final_language_build", False):
        async def build_embed(self):
            embed = await current_build(self)
            language = await language_runtime.get_language(self.bot, self.guild_id)
            if language == language_runtime.LANG_EN:
                language_runtime._translate_setup_embed(embed)
            if getattr(self, "page", None) == -1:
                # Evite un doublon si une ancienne couche de langue a déjà ajouté le champ.
                for index in range(len(embed.fields) - 1, -1, -1):
                    if str(embed.fields[index].name or "").strip() in {"🌐 Langue", "🌐 Language"}:
                        embed.remove_field(index)
                label = "English" if language == language_runtime.LANG_EN else "Francais"
                embed.add_field(
                    name="🌐 Language" if language == language_runtime.LANG_EN else "🌐 Langue",
                    value=(
                        f"Current language: **{label}**"
                        if language == language_runtime.LANG_EN
                        else f"Langue actuelle : **{label}**"
                    ),
                    inline=False,
                )
            return embed

        build_embed._sentrix_final_language_build = True
        view_cls.build_embed = build_embed

    current_render = view_cls.render_page
    if not getattr(current_render, "_sentrix_final_language_render", False):
        def render_page(self):
            current_render(self)
            language = language_runtime.cached_language(self.bot, self.guild_id)

            # Nettoie un éventuel sélecteur hérité avant d'ajouter le sélecteur final.
            for item in list(self.children):
                if isinstance(item, discord.ui.Select):
                    values = {str(getattr(option, "value", "")) for option in getattr(item, "options", [])}
                    if values == {language_runtime.LANG_FR, language_runtime.LANG_EN}:
                        self.remove_item(item)

            if language == language_runtime.LANG_EN:
                for item in self.children:
                    if isinstance(item, discord.ui.Button):
                        item.label = language_runtime._english_setup_text(item.label)
                    elif isinstance(item, discord.ui.Select):
                        item.placeholder = language_runtime._english_setup_text(item.placeholder)
                        for option in item.options:
                            option.label = language_runtime._english_setup_text(option.label)
                            option.description = language_runtime._english_setup_text(option.description)

            if getattr(self, "page", None) != -1:
                return

            selector = discord.ui.Select(
                placeholder="🌐 Language / Langue",
                min_values=1,
                max_values=1,
                options=[
                    discord.SelectOption(
                        label="🇫🇷 Francais",
                        value=language_runtime.LANG_FR,
                        description="Noms de commandes et interfaces en francais",
                    ),
                    discord.SelectOption(
                        label="🇬🇧 English",
                        value=language_runtime.LANG_EN,
                        description="Command names and interfaces in English",
                    ),
                ],
                row=3,
            )

            async def language_callback(interaction: discord.Interaction):
                member = interaction.user
                if not isinstance(member, discord.Member) or (
                    not member.guild_permissions.administrator
                    and member.id != interaction.guild.owner_id
                ):
                    return await interaction.response.send_message(
                        "Administrator permission required. / Permission Administrateur requise.",
                        ephemeral=True,
                    )
                await language_runtime.set_language(self.bot, self.guild_id, selector.values[0])
                self.render_page()
                await interaction.response.edit_message(embed=await self.build_embed(), view=self)

            selector.callback = language_callback
            self.add_item(selector)

        render_page._sentrix_final_language_render = True
        view_cls.render_page = render_page

    logger.info("Langue +setup finalisée après les couches de style/tickets.")
