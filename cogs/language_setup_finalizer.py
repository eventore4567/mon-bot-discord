"""Applique la langue sur la version FINALE de +setup.

La langue doit apparaitre comme une vraie entree du menu des categories de +setup.
Les autres couches UI peuvent remplacer render_page/build_embed ; ce finaliseur est donc
applique en dernier et transforme le menu principal sans modifier la logique des autres
modules.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from . import language_runtime

logger = logging.getLogger("bot.language-setup-finalizer")
LANGUAGE_CATEGORY_VALUE = "__sentrix_language__"


def _is_language_select(item) -> bool:
    if not isinstance(item, discord.ui.Select):
        return False
    values = {str(getattr(option, "value", "")) for option in getattr(item, "options", [])}
    return values == {language_runtime.LANG_FR, language_runtime.LANG_EN}


def _is_category_select(item) -> bool:
    if not isinstance(item, discord.ui.Select):
        return False
    options = list(getattr(item, "options", []) or [])
    if not options:
        return False
    values = [str(getattr(option, "value", "")) for option in options]
    return all(value.isdigit() for value in values)


def _can_change_language(interaction: discord.Interaction) -> bool:
    member = interaction.user
    return bool(
        isinstance(member, discord.Member)
        and interaction.guild is not None
        and (member.guild_permissions.administrator or member.id == interaction.guild.owner_id)
    )


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

            # Les anciennes versions ajoutaient un bouton et un select FR/EN separes.
            # On les retire : la langue vit maintenant DANS le menu Categories.
            for item in list(self.children):
                if _is_language_select(item):
                    self.remove_item(item)
                    continue
                label = str(getattr(item, "label", "") or "")
                if getattr(item, "custom_id", None) == "sentrix:setup:language" or label in {
                    "🌐 Langue", "🌐 Language", "🌐 Langue / Language"
                }:
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

            category_select = next((item for item in self.children if _is_category_select(item)), None)
            if category_select is None:
                logger.error("Impossible de trouver le menu Categories de +setup pour y ajouter la langue.")
                return

            option_label = "🌐 Server language" if language == language_runtime.LANG_EN else "🌐 Langue du serveur"
            option_description = (
                "Choose French or English for SentriX."
                if language == language_runtime.LANG_EN
                else "Choisir Francais ou English pour SentriX."
            )
            category_select.append_option(
                discord.SelectOption(
                    label=option_label,
                    value=LANGUAGE_CATEGORY_VALUE,
                    description=option_description,
                )
            )
            original_callback = category_select.callback

            async def category_callback(interaction: discord.Interaction):
                if not category_select.values or category_select.values[0] != LANGUAGE_CATEGORY_VALUE:
                    return await original_callback(interaction)

                if not _can_change_language(interaction):
                    return await interaction.response.send_message(
                        "Administrator permission required. / Permission Administrateur requise.",
                        ephemeral=True,
                    )

                picker = discord.ui.View(timeout=90)
                fr_button = discord.ui.Button(
                    label="Francais",
                    emoji="🇫🇷",
                    style=discord.ButtonStyle.primary,
                )
                en_button = discord.ui.Button(
                    label="English",
                    emoji="🇬🇧",
                    style=discord.ButtonStyle.secondary,
                )

                async def choose_language(choice_interaction: discord.Interaction, choice: str):
                    if not _can_change_language(choice_interaction):
                        return await choice_interaction.response.send_message(
                            "Administrator permission required. / Permission Administrateur requise.",
                            ephemeral=True,
                        )
                    await language_runtime.set_language(self.bot, self.guild_id, choice)
                    self.render_page()
                    chosen_label = "English" if choice == language_runtime.LANG_EN else "Francais"
                    confirmation = discord.Embed(
                        title="🌐 Language changed" if choice == language_runtime.LANG_EN else "🌐 Langue modifiee",
                        description=(
                            f"Server language is now **{chosen_label}**."
                            if choice == language_runtime.LANG_EN
                            else f"La langue du serveur est maintenant **{chosen_label}**."
                        ),
                        color=0x8B5CF6,
                    )
                    await choice_interaction.response.edit_message(embed=confirmation, view=None)

                    # Rafraichit aussi le vrai +setup pour que la categorie et tout le panneau
                    # passent immediatement dans la nouvelle langue.
                    try:
                        channel = self.bot.get_channel(self.channel_id)
                        if channel is not None:
                            message = await channel.fetch_message(self.message_id)
                            await message.edit(embed=await self.build_embed(), view=self)
                    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                        logger.exception("Langue changee mais rafraichissement du panneau +setup impossible.")

                async def choose_fr(choice_interaction: discord.Interaction):
                    await choose_language(choice_interaction, language_runtime.LANG_FR)

                async def choose_en(choice_interaction: discord.Interaction):
                    await choose_language(choice_interaction, language_runtime.LANG_EN)

                fr_button.callback = choose_fr
                en_button.callback = choose_en
                picker.add_item(fr_button)
                picker.add_item(en_button)

                title = "🌐 Choose the server language" if language == language_runtime.LANG_EN else "🌐 Choisir la langue du serveur"
                text = (
                    "Choose **English** or **Francais** below."
                    if language == language_runtime.LANG_EN
                    else "Choisis **Francais** ou **English** ci-dessous."
                )
                await interaction.response.send_message(
                    embed=discord.Embed(title=title, description=text, color=0x8B5CF6),
                    view=picker,
                    ephemeral=True,
                )

            category_select.callback = category_callback

        render_page._sentrix_final_language_render = True
        view_cls.render_page = render_page

    logger.info("Langue +setup finalisee : entree Langue ajoutee directement au menu Categories.")
