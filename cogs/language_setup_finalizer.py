"""Langue FR/EN de +setup, garantie jusque dans le payload envoyé à Discord.

Le menu de langue a déjà été ajouté à plusieurs couches de rendu. Le problème réel est
qu'un autre renderer peut reconstruire le Select après ces patches. Cette version agit
également au dernier moment, dans ``View.to_components()``, juste avant que discord.py
sérialise les composants. Si l'accueil +setup est envoyé, ``🌐 Langue du serveur`` est donc
forcément la PREMIÈRE option du vrai menu Catégories.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from . import language_runtime

logger = logging.getLogger("bot.language-setup-finalizer")
LANGUAGE_CATEGORY_VALUE = "__sentrix_language__"
LANGUAGE_PAGE = -20260809


def _can_change_language(interaction: discord.Interaction) -> bool:
    member = interaction.user
    return bool(
        isinstance(member, discord.Member)
        and interaction.guild is not None
        and (member.guild_permissions.administrator or member.id == interaction.guild.owner_id)
    )


def _language_text(language: str) -> tuple[str, str]:
    if language == language_runtime.LANG_EN:
        return "🌐 Server language", "Choose French or English for SentriX."
    return "🌐 Langue du serveur", "Choisir Français ou English pour SentriX."


def _remove_old_language_controls(view) -> None:
    """Retire les anciens contrôles FR/EN séparés. La langue reste uniquement en Catégories."""
    for item in list(view.children):
        if isinstance(item, discord.ui.Select):
            values = {
                str(getattr(option, "value", ""))
                for option in getattr(item, "options", [])
            }
            if values == {language_runtime.LANG_FR, language_runtime.LANG_EN}:
                view.remove_item(item)
                continue

        label = str(getattr(item, "label", "") or "")
        if getattr(item, "custom_id", None) == "sentrix:setup:language" or label in {
            "🌐 Langue", "🌐 Language", "🌐 Langue / Language"
        }:
            view.remove_item(item)


def _find_category_select(view) -> discord.ui.Select | None:
    """Repère le menu principal de +setup à partir de ses valeurs numériques historiques."""
    found: list[discord.ui.Select] = []
    for item in view.children:
        if not isinstance(item, discord.ui.Select):
            continue
        options = list(getattr(item, "options", []) or [])
        if not options:
            continue
        numeric_count = sum(
            1 for option in options
            if str(getattr(option, "value", "")).isdigit()
        )
        if numeric_count >= 3:
            found.append(item)

    return max(found, key=lambda item: len(item.options)) if found else None


def _ensure_language_option(view, language: str) -> bool:
    """Insère Langue en PREMIER dans le Select Catégories réellement sérialisé."""
    select = _find_category_select(view)
    if select is None:
        logger.error("+setup: Select Catégories introuvable juste avant envoi Discord.")
        return False

    # Mutation EN PLACE de la liste interne : on ne dépend pas d'un setter de discord.py.
    options = select.options
    options[:] = [
        option for option in options
        if str(getattr(option, "value", "")) != LANGUAGE_CATEGORY_VALUE
    ]

    if len(options) >= 25:
        logger.error("+setup: Select Catégories plein, impossible d'insérer la langue.")
        return False

    label, description = _language_text(language)
    options.insert(
        0,
        discord.SelectOption(
            label=label,
            value=LANGUAGE_CATEGORY_VALUE,
            description=description,
        ),
    )

    # Le callback est attaché au Select final. Les autres catégories continuent d'utiliser
    # exactement leur callback d'origine.
    if not getattr(select, "_sentrix_language_callback", False):
        original_callback = select.callback

        async def callback(interaction: discord.Interaction):
            selected = select.values[0] if select.values else None
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

        select.callback = callback
        select._sentrix_language_callback = True

    return True


def _render_language_page(view, language: str) -> None:
    view.clear_items()

    fr = discord.ui.Button(
        label="Français",
        emoji="🇫🇷",
        style=discord.ButtonStyle.success if language == language_runtime.LANG_FR else discord.ButtonStyle.secondary,
        custom_id="sentrix:setup:lang:fr",
        row=0,
    )
    en = discord.ui.Button(
        label="English",
        emoji="🇬🇧",
        style=discord.ButtonStyle.success if language == language_runtime.LANG_EN else discord.ButtonStyle.secondary,
        custom_id="sentrix:setup:lang:en",
        row=0,
    )
    home = discord.ui.Button(
        label="🏠 Home" if language == language_runtime.LANG_EN else "🏠 Accueil",
        style=discord.ButtonStyle.secondary,
        custom_id="sentrix:setup:lang:home",
        row=1,
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
            logger.debug("+setup: session non persistée après changement de langue.", exc_info=True)
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

    fr.callback = choose_fr
    en.callback = choose_en
    home.callback = go_home
    view.add_item(fr)
    view.add_item(en)
    view.add_item(home)


def _language_embed(language: str) -> discord.Embed:
    current = "English" if language == language_runtime.LANG_EN else "Français"
    if language == language_runtime.LANG_EN:
        embed = discord.Embed(
            title="🌐 Server language",
            description="Choose the language SentriX should use on this server.",
            color=0x8B5CF6,
        )
        embed.add_field(name="Current language", value=f"**{current}**", inline=False)
    else:
        embed = discord.Embed(
            title="🌐 Langue du serveur",
            description="Choisis la langue que SentriX doit utiliser sur ce serveur.",
            color=0x8B5CF6,
        )
        embed.add_field(name="Langue actuelle", value=f"**{current}**", inline=False)

    embed.add_field(
        name="Available choices" if language == language_runtime.LANG_EN else "Choix disponibles",
        value="🇫🇷 **Français**\n🇬🇧 **English**",
        inline=False,
    )
    return embed


def install(bot: commands.Bot) -> None:
    try:
        from . import configuration
    except Exception:
        return

    view_cls = getattr(configuration, "SetupView", None)
    if view_cls is None:
        return

    # Premier rendu / retour accueil.
    current_init = view_cls.__init__
    if not getattr(current_init, "_sentrix_language_wire_init", False):
        def init(self, *args, **kwargs):
            current_init(self, *args, **kwargs)
            if getattr(self, "page", None) == -1:
                _remove_old_language_controls(self)
                _ensure_language_option(self, language_runtime.cached_language(self.bot, self.guild_id))

        init._sentrix_language_wire_init = True
        view_cls.__init__ = init

    current_home = view_cls._render_home
    if not getattr(current_home, "_sentrix_language_wire_home", False):
        def render_home(self):
            current_home(self)
            _remove_old_language_controls(self)
            _ensure_language_option(self, language_runtime.cached_language(self.bot, self.guild_id))

        render_home._sentrix_language_wire_home = True
        view_cls._render_home = render_home

    current_render = view_cls.render_page
    if not getattr(current_render, "_sentrix_language_wire_render", False):
        def render_page(self):
            language = language_runtime.cached_language(self.bot, self.guild_id)
            if getattr(self, "page", None) == LANGUAGE_PAGE:
                _render_language_page(self, language)
                return

            current_render(self)
            _remove_old_language_controls(self)
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

        render_page._sentrix_language_wire_render = True
        view_cls.render_page = render_page

    # GARDE-FEU FINAL : discord.py appelle to_components() juste avant d'envoyer la vue.
    # Même si une autre couche a reconstruit le Select après render_page, la langue est
    # réinsérée ici dans le payload réellement transmis à Discord.
    current_to_components = view_cls.to_components
    if not getattr(current_to_components, "_sentrix_language_final_wire", False):
        def to_components(self):
            if getattr(self, "page", None) == -1:
                _remove_old_language_controls(self)
                _ensure_language_option(self, language_runtime.cached_language(self.bot, self.guild_id))
            return current_to_components(self)

        to_components._sentrix_language_final_wire = True
        view_cls.to_components = to_components

    current_build = view_cls.build_embed
    if not getattr(current_build, "_sentrix_language_wire_build", False):
        async def build_embed(self):
            language = await language_runtime.get_language(self.bot, self.guild_id)
            if getattr(self, "page", None) == LANGUAGE_PAGE:
                return _language_embed(language)

            embed = await current_build(self)
            if language == language_runtime.LANG_EN:
                language_runtime._translate_setup_embed(embed)

            if getattr(self, "page", None) == -1:
                # Marqueur visible : si ce champ n'est pas présent, le message observé vient
                # d'un ancien panneau/ancienne instance et non du nouveau renderer.
                for index in range(len(embed.fields) - 1, -1, -1):
                    if str(embed.fields[index].name or "").strip() in {"🌐 Langue", "🌐 Language"}:
                        embed.remove_field(index)
                current = "English" if language == language_runtime.LANG_EN else "Français"
                embed.add_field(
                    name="🌐 Language" if language == language_runtime.LANG_EN else "🌐 Langue",
                    value=(
                        f"Current: **{current}** • first option in **Categories**."
                        if language == language_runtime.LANG_EN
                        else f"Actuelle : **{current}** • première option dans **Catégories**."
                    ),
                    inline=False,
                )
            return embed

        build_embed._sentrix_language_wire_build = True
        view_cls.build_embed = build_embed

    # Marqueur de diagnostic pour les audits et les futurs correctifs.
    view_cls._sentrix_language_patch = True
    view_cls._sentrix_language_payload_guard = True
    logger.info(
        "+setup FR/EN final-wire actif : Langue est forcée en 1re option au moment de la sérialisation Discord."
    )
