"""Rend le choix FR/EN impossible à perdre dans +setup.

Ce correctif ne dépend plus de SETUP_STEPS ni d'un index de page ajouté à chaud.
Il enveloppe directement le rendu FINAL de l'accueil +setup et force l'option Langue
dans le vrai menu Catégories affiché à Discord. Le constructeur, _render_home et
render_page sont tous couverts afin qu'aucune couche visuelle ne puisse contourner
le réglage.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from . import language_runtime

logger = logging.getLogger("bot.language-setup-finalizer")

# Valeur spéciale utilisée uniquement dans le Select Catégories. Elle n'entre jamais dans
# les index historiques de SETUP_STEPS et ne peut donc pas casser une ancienne session.
LANGUAGE_CATEGORY_VALUE = "__sentrix_language__"
LANGUAGE_PAGE = -20260809


def _can_change_language(interaction: discord.Interaction) -> bool:
    member = interaction.user
    return bool(
        isinstance(member, discord.Member)
        and interaction.guild is not None
        and (member.guild_permissions.administrator or member.id == interaction.guild.owner_id)
    )


def _language_label(language: str) -> tuple[str, str]:
    if language == language_runtime.LANG_EN:
        return "🌐 Server language", "Choose French or English for SentriX."
    return "🌐 Langue du serveur", "Choisir Français ou English pour SentriX."


def _remove_legacy_language_controls(view) -> None:
    """Nettoie les anciens boutons/selects de langue séparés des versions précédentes."""
    for item in list(view.children):
        if isinstance(item, discord.ui.Select):
            values = {str(getattr(option, "value", "")) for option in getattr(item, "options", [])}
            if values == {language_runtime.LANG_FR, language_runtime.LANG_EN}:
                view.remove_item(item)
                continue
        label = str(getattr(item, "label", "") or "")
        if getattr(item, "custom_id", None) == "sentrix:setup:language" or label in {
            "🌐 Langue", "🌐 Language", "🌐 Langue / Language"
        }:
            view.remove_item(item)


def _find_category_select(view) -> discord.ui.Select | None:
    """Trouve le vrai menu principal Catégories sans dépendre de son placeholder."""
    candidates: list[discord.ui.Select] = []
    for item in view.children:
        if not isinstance(item, discord.ui.Select):
            continue
        options = list(getattr(item, "options", []) or [])
        if not options:
            continue
        values = [str(getattr(option, "value", "")) for option in options]
        # Le menu historique de +setup utilise des index numériques pour ses catégories.
        numeric = sum(1 for value in values if value.isdigit())
        if numeric >= 3:
            candidates.append(item)

    if not candidates:
        return None
    # Le menu principal est celui qui contient le plus de catégories.
    return max(candidates, key=lambda item: len(getattr(item, "options", []) or []))


def _ensure_language_option(view, language: str) -> bool:
    """Force Langue dans le Select réellement affiché et intercepte uniquement ce choix."""
    category_select = _find_category_select(view)
    if category_select is None:
        logger.error("+setup: menu Catégories introuvable, impossible d'ajouter Langue.")
        return False

    # Enlève toute ancienne copie avant de rajouter exactement une option.
    kept = [
        option for option in list(category_select.options)
        if str(getattr(option, "value", "")) != LANGUAGE_CATEGORY_VALUE
    ]
    category_select.options = kept

    if len(category_select.options) >= 25:
        logger.error("+setup: menu Catégories plein (25 options), Langue ne peut pas être ajoutée.")
        return False

    label, description = _language_label(language)
    category_select.append_option(
        discord.SelectOption(
            label=label,
            value=LANGUAGE_CATEGORY_VALUE,
            description=description,
            emoji="🌐",
        )
    )

    # Chaque nouveau rendu crée un Select neuf. On conserve son callback normal et on
    # intercepte seulement la valeur spéciale Langue.
    if not getattr(category_select, "_sentrix_language_callback", False):
        original_callback = category_select.callback

        async def category_callback(interaction: discord.Interaction):
            selected = category_select.values[0] if category_select.values else None
            if selected != LANGUAGE_CATEGORY_VALUE:
                return await original_callback(interaction)

            if not _can_change_language(interaction):
                return await interaction.response.send_message(
                    "Permission Administrateur requise. / Administrator permission required.",
                    ephemeral=True,
                )

            view.page = LANGUAGE_PAGE
            view.render_page()
            await view._refresh_message(interaction)

        category_select.callback = category_callback
        category_select._sentrix_language_callback = True

    return True


def _render_language_controls(view, language: str) -> None:
    view.clear_items()

    fr_button = discord.ui.Button(
        label="Français",
        emoji="🇫🇷",
        style=(discord.ButtonStyle.success if language == language_runtime.LANG_FR else discord.ButtonStyle.secondary),
        row=0,
        custom_id="sentrix:setup:lang:fr",
    )
    en_button = discord.ui.Button(
        label="English",
        emoji="🇬🇧",
        style=(discord.ButtonStyle.success if language == language_runtime.LANG_EN else discord.ButtonStyle.secondary),
        row=0,
        custom_id="sentrix:setup:lang:en",
    )
    home_button = discord.ui.Button(
        label="🏠 Home" if language == language_runtime.LANG_EN else "🏠 Accueil",
        style=discord.ButtonStyle.secondary,
        row=1,
        custom_id="sentrix:setup:lang:home",
    )

    async def choose(interaction: discord.Interaction, choice: str):
        if not _can_change_language(interaction):
            return await interaction.response.send_message(
                "Permission Administrateur requise. / Administrator permission required.",
                ephemeral=True,
            )
        await language_runtime.set_language(view.bot, view.guild_id, choice)
        view.page = -1
        try:
            await view.persist_session()
        except Exception:
            logger.debug("+setup: impossible de persister le retour accueil après langue.", exc_info=True)
        view.render_page()
        await view._refresh_message(interaction)

    async def choose_fr(interaction: discord.Interaction):
        await choose(interaction, language_runtime.LANG_FR)

    async def choose_en(interaction: discord.Interaction):
        await choose(interaction, language_runtime.LANG_EN)

    async def go_home(interaction: discord.Interaction):
        view.page = -1
        view.render_page()
        await view._refresh_message(interaction)

    fr_button.callback = choose_fr
    en_button.callback = choose_en
    home_button.callback = go_home
    view.add_item(fr_button)
    view.add_item(en_button)
    view.add_item(home_button)


def _language_embed(language: str) -> discord.Embed:
    current = "English" if language == language_runtime.LANG_EN else "Français"
    if language == language_runtime.LANG_EN:
        embed = discord.Embed(
            title="🌐 Server language",
            description="Choose the language SentriX should use on this server.",
            color=0x8B5CF6,
        )
        embed.add_field(name="Current language", value=f"**{current}**", inline=False)
        embed.add_field(
            name="Available choices",
            value="🇫🇷 **Français**\n🇬🇧 **English**",
            inline=False,
        )
        return embed

    embed = discord.Embed(
        title="🌐 Langue du serveur",
        description="Choisis la langue que SentriX doit utiliser sur ce serveur.",
        color=0x8B5CF6,
    )
    embed.add_field(name="Langue actuelle", value=f"**{current}**", inline=False)
    embed.add_field(
        name="Choix disponibles",
        value="🇫🇷 **Français**\n🇬🇧 **English**",
        inline=False,
    )
    return embed


def install(bot: commands.Bot) -> None:
    del bot
    try:
        from . import configuration
    except Exception:
        return

    view_cls = getattr(configuration, "SetupView", None)
    if view_cls is None:
        return

    # 1) Le constructeur est couvert : même si SetupView appelle _render_home directement,
    # l'option Langue est présente sur le tout premier message envoyé.
    current_init = view_cls.__init__
    if not getattr(current_init, "_sentrix_language_init_hardfix", False):
        def init_with_language(self, *args, **kwargs):
            current_init(self, *args, **kwargs)
            if getattr(self, "page", None) == -1:
                _remove_legacy_language_controls(self)
                _ensure_language_option(self, language_runtime.cached_language(self.bot, self.guild_id))

        init_with_language._sentrix_language_init_hardfix = True
        view_cls.__init__ = init_with_language

    # 2) L'accueil lui-même est couvert : retour Accueil, reconstruction et vieux panneaux.
    current_home = view_cls._render_home
    if not getattr(current_home, "_sentrix_language_home_hardfix", False):
        def home_with_language(self):
            current_home(self)
            _remove_legacy_language_controls(self)
            _ensure_language_option(self, language_runtime.cached_language(self.bot, self.guild_id))

        home_with_language._sentrix_language_home_hardfix = True
        view_cls._render_home = home_with_language

    # 3) render_page est couvert pour la page virtuelle Langue et comme dernier filet
    # de sécurité si une autre couche a reconstruit l'accueil sans passer par _render_home.
    current_render = view_cls.render_page
    if not getattr(current_render, "_sentrix_language_render_hardfix", False):
        def render_with_language(self):
            language = language_runtime.cached_language(self.bot, self.guild_id)
            if getattr(self, "page", None) == LANGUAGE_PAGE:
                _render_language_controls(self, language)
                return

            current_render(self)
            _remove_legacy_language_controls(self)
            if getattr(self, "page", None) == -1:
                _ensure_language_option(self, language)

            if language == language_runtime.LANG_EN:
                for item in self.children:
                    if isinstance(item, discord.ui.Button):
                        item.label = language_runtime._english_setup_text(item.label)
                    elif isinstance(item, discord.ui.Select):
                        item.placeholder = language_runtime._english_setup_text(item.placeholder)
                        for option in item.options:
                            if str(getattr(option, "value", "")) == LANGUAGE_CATEGORY_VALUE:
                                continue
                            option.label = language_runtime._english_setup_text(option.label)
                            option.description = language_runtime._english_setup_text(option.description)

        render_with_language._sentrix_language_render_hardfix = True
        view_cls.render_page = render_with_language

    # 4) L'embed final est couvert indépendamment de toutes les couches de style.
    current_build = view_cls.build_embed
    if not getattr(current_build, "_sentrix_language_build_hardfix", False):
        async def build_with_language(self):
            language = await language_runtime.get_language(self.bot, self.guild_id)
            if getattr(self, "page", None) == LANGUAGE_PAGE:
                return _language_embed(language)

            embed = await current_build(self)
            if language == language_runtime.LANG_EN:
                language_runtime._translate_setup_embed(embed)

            if getattr(self, "page", None) == -1:
                for index in range(len(embed.fields) - 1, -1, -1):
                    if str(embed.fields[index].name or "").strip() in {"🌐 Langue", "🌐 Language"}:
                        embed.remove_field(index)
                current = "English" if language == language_runtime.LANG_EN else "Français"
                embed.add_field(
                    name="🌐 Language" if language == language_runtime.LANG_EN else "🌐 Langue",
                    value=(
                        f"Current language: **{current}** — open **Categories → Server language**."
                        if language == language_runtime.LANG_EN
                        else f"Langue actuelle : **{current}** — ouvre **Catégories → Langue du serveur**."
                    ),
                    inline=False,
                )
            return embed

        build_with_language._sentrix_language_build_hardfix = True
        view_cls.build_embed = build_with_language

    logger.info(
        "+setup FR/EN réécrit : Langue forcée dans le Select final (constructeur + accueil + render_page)."
    )
