"""Intègre le choix de langue comme une VRAIE catégorie de +setup.

Les versions précédentes ajoutaient une option au Select après sa construction. En test
cela fonctionnait, mais le rendu réel pouvait passer par une autre couche de +setup. Ici,
la langue est injectée directement dans SETUP_STEPS : toutes les versions du menu
(configuration de base, style premium, reconstruction de session) la voient donc comme
une catégorie normale.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from . import language_runtime

logger = logging.getLogger("bot.language-setup-finalizer")
LANGUAGE_CATEGORY_VALUE = "__sentrix_language__"  # rétrocompatibilité avec les anciens panneaux
LANGUAGE_STEP_KEY = "language"


def _can_change_language(interaction: discord.Interaction) -> bool:
    member = interaction.user
    return bool(
        isinstance(member, discord.Member)
        and interaction.guild is not None
        and (member.guild_permissions.administrator or member.id == interaction.guild.owner_id)
    )


def _ensure_native_language_step(configuration) -> int:
    """Ajoute la langue à la source de vérité du menu, sans déplacer les anciennes pages."""
    for index, step in enumerate(configuration.SETUP_STEPS):
        if step.get("key") == LANGUAGE_STEP_KEY:
            return index

    # On ajoute APRES les étapes existantes (y compris summary) afin de ne jamais changer
    # les index sauvegardés d'une session +setup déjà ouverte avant un redéploiement.
    configuration.SETUP_STEPS.append({
        "key": LANGUAGE_STEP_KEY,
        "icon": "🌐",
        "title": "Langue du serveur",
        "description": "Choisir Français ou English pour les commandes et interfaces SentriX.",
        "fields": [],
        "custom": "language",
    })

    # Le thème premium lit STEP_META directement au moment où il construit le menu.
    # L'ajout ici rend donc la catégorie native même si le thème a déjà été installé.
    try:
        from . import setup_oxyde_style
        setup_oxyde_style.STEP_META.setdefault(LANGUAGE_STEP_KEY, {
            "title": "Langue du serveur",
            "summary": "Choisis Français ou English pour SentriX sur ce serveur.",
            "details": "Le choix adapte les noms des commandes préfixées, l'aide et les interfaces prises en charge.",
            "tip": "Tu peux revenir ici à tout moment pour changer la langue du serveur.",
        })
    except Exception:
        logger.debug("STEP_META indisponible pendant l'ajout de la langue.", exc_info=True)

    return len(configuration.SETUP_STEPS) - 1


def _language_step_index(configuration) -> int | None:
    for index, step in enumerate(configuration.SETUP_STEPS):
        if step.get("key") == LANGUAGE_STEP_KEY:
            return index
    return None


def _remove_legacy_language_controls(view) -> None:
    """Retire seulement les anciens contrôles FR/EN séparés des PR précédentes."""
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


def _localize_native_option(view, language: str, language_index: int) -> None:
    target_value = str(language_index)
    for item in view.children:
        if not isinstance(item, discord.ui.Select):
            continue
        for option in getattr(item, "options", []):
            if str(getattr(option, "value", "")) != target_value:
                continue
            if language == language_runtime.LANG_EN:
                option.label = "🌐 Server language"
                option.description = "Choose French or English for SentriX."
            else:
                option.label = "🌐 Langue du serveur"
                option.description = "Choisir Français ou English pour SentriX."


def _render_language_controls(self, configuration, language: str) -> None:
    self.clear_items()

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

    async def choose(choice_interaction: discord.Interaction, choice: str):
        if not _can_change_language(choice_interaction):
            return await choice_interaction.response.send_message(
                "Administrator permission required. / Permission Administrateur requise.",
                ephemeral=True,
            )
        await language_runtime.set_language(self.bot, self.guild_id, choice)
        self.page = -1
        try:
            await self.persist_session()
        except Exception:
            logger.debug("Impossible de persister la page après changement de langue.", exc_info=True)
        self.render_page()
        await self._refresh_message(choice_interaction)

    async def choose_fr(interaction: discord.Interaction):
        await choose(interaction, language_runtime.LANG_FR)

    async def choose_en(interaction: discord.Interaction):
        await choose(interaction, language_runtime.LANG_EN)

    fr_button.callback = choose_fr
    en_button.callback = choose_en
    self.add_item(fr_button)
    self.add_item(en_button)

    # Le bouton dynamique Home reste compatible avec les sessions reconstruites après un redémarrage.
    self.add_item(configuration.SetupNavButton(
        "home",
        self.message_id,
        label="🏠 Home" if language == language_runtime.LANG_EN else "🏠 Accueil",
        style=discord.ButtonStyle.secondary,
        row=1,
    ))


def install(bot: commands.Bot) -> None:
    del bot
    try:
        from . import configuration
    except Exception:
        return

    view_cls = getattr(configuration, "SetupView", None)
    if view_cls is None:
        return

    language_index = _ensure_native_language_step(configuration)

    current_build = view_cls.build_embed
    if not getattr(current_build, "_sentrix_native_language_build", False):
        async def build_embed(self):
            current_index = _language_step_index(configuration)
            language = await language_runtime.get_language(self.bot, self.guild_id)

            # La page Langue est construite ici sans passer par les anciens renderers qui
            # ne connaissent pas cette nouvelle étape native.
            if current_index is not None and getattr(self, "page", None) == current_index:
                current_label = "English" if language == language_runtime.LANG_EN else "Français"
                if language == language_runtime.LANG_EN:
                    embed = discord.Embed(
                        title="🌐 Server language",
                        description="Choose the language SentriX should use on this server.",
                        color=0x8B5CF6,
                    )
                    embed.add_field(name="Current language", value=f"**{current_label}**", inline=False)
                    embed.add_field(
                        name="What changes",
                        value="Command names shown by help and supported SentriX interfaces follow this choice.",
                        inline=False,
                    )
                else:
                    embed = discord.Embed(
                        title="🌐 Langue du serveur",
                        description="Choisis la langue que SentriX doit utiliser sur ce serveur.",
                        color=0x8B5CF6,
                    )
                    embed.add_field(name="Langue actuelle", value=f"**{current_label}**", inline=False)
                    embed.add_field(
                        name="Ce qui change",
                        value="Les noms affichés dans l'aide et les interfaces SentriX prises en charge suivent ce choix.",
                        inline=False,
                    )
                return embed

            embed = await current_build(self)
            if language == language_runtime.LANG_EN:
                language_runtime._translate_setup_embed(embed)

            if getattr(self, "page", None) == -1:
                # Un seul rappel discret dans l'embed ; le vrai réglage se trouve dans Catégories.
                for index in range(len(embed.fields) - 1, -1, -1):
                    if str(embed.fields[index].name or "").strip() in {"🌐 Langue", "🌐 Language"}:
                        embed.remove_field(index)
                label = "English" if language == language_runtime.LANG_EN else "Français"
                embed.add_field(
                    name="🌐 Language" if language == language_runtime.LANG_EN else "🌐 Langue",
                    value=(
                        f"Current language: **{label}** — change it from **Categories → Server language**."
                        if language == language_runtime.LANG_EN
                        else f"Langue actuelle : **{label}** — change-la dans **Catégories → Langue du serveur**."
                    ),
                    inline=False,
                )
            return embed

        build_embed._sentrix_native_language_build = True
        view_cls.build_embed = build_embed

    current_render = view_cls.render_page
    if not getattr(current_render, "_sentrix_native_language_render", False):
        def render_page(self):
            current_index = _language_step_index(configuration)
            language = language_runtime.cached_language(self.bot, self.guild_id)

            if current_index is not None and getattr(self, "page", None) == current_index:
                _render_language_controls(self, configuration, language)
                return

            current_render(self)
            _remove_legacy_language_controls(self)

            if language == language_runtime.LANG_EN:
                for item in self.children:
                    if isinstance(item, discord.ui.Button):
                        item.label = language_runtime._english_setup_text(item.label)
                    elif isinstance(item, discord.ui.Select):
                        item.placeholder = language_runtime._english_setup_text(item.placeholder)
                        for option in item.options:
                            option.label = language_runtime._english_setup_text(option.label)
                            option.description = language_runtime._english_setup_text(option.description)

            if getattr(self, "page", None) == -1 and current_index is not None:
                _localize_native_option(self, language, current_index)

        render_page._sentrix_native_language_render = True
        view_cls.render_page = render_page

    logger.info(
        "Langue +setup finalisée : étape native #%s dans SETUP_STEPS, visible dans le menu Catégories.",
        language_index,
    )
