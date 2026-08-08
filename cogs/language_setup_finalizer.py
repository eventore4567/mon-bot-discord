"""Rendu final de +setup et nettoyage des anciennes commandes slash locales.

Cette couche est volontairement la dernière autorité sur l'accueil de +setup :
- Langue / Server language est une vraie catégorie, toujours première ;
- le panneau est réappliqué juste après sa création, pas seulement via un patch de classe ;
- les anciennes copies de commandes slash créées par +syncguild sont supprimées au ready ;
- +syncguild ne recrée plus de copies locales qui apparaissent en double dans Discord.
"""
from __future__ import annotations

import logging
import os

import discord
from discord.ext import commands

from utils import embeds
from . import language_runtime

logger = logging.getLogger("bot.language-setup-finalizer")

LANGUAGE_CATEGORY_VALUE = "__sentrix_language__"
LANGUAGE_PAGE = -20260809
_SETUP_BUILD_MARKER = "Interface setup v4"


def _can_change_language(interaction: discord.Interaction) -> bool:
    member = interaction.user
    return bool(
        isinstance(member, discord.Member)
        and interaction.guild is not None
        and (member.guild_permissions.administrator or member.id == interaction.guild.owner_id)
    )


def _is_english(view) -> bool:
    return language_runtime.cached_language(view.bot, view.guild_id) == language_runtime.LANG_EN


def _step_meta(step: dict) -> tuple[str, str]:
    try:
        from . import setup_oxyde_style
        meta = setup_oxyde_style.STEP_META.get(step.get("key"), {})
    except Exception:
        meta = {}

    title = str(meta.get("title") or step.get("title") or step.get("key") or "Configuration")
    summary = str(meta.get("summary") or step.get("description") or "Configurer ce module.")
    return title, summary


def _language_embed(view) -> discord.Embed:
    english = _is_english(view)
    current = "English" if english else "Français"
    if english:
        embed = discord.Embed(
            title="🌐 Server language",
            description=(
                "Choose the language used by SentriX for command names, help and the main "
                "configuration interfaces on this server."
            ),
            color=0x8B5CF6,
        )
        embed.add_field(name="Current language", value=f"**{current}**", inline=False)
        embed.add_field(name="Available languages", value="🇫🇷 **Français**\n🇬🇧 **English**", inline=False)
    else:
        embed = discord.Embed(
            title="🌐 Langue du serveur",
            description=(
                "Choisis la langue utilisée par SentriX pour les noms de commandes, l'aide "
                "et les principales interfaces de configuration de ce serveur."
            ),
            color=0x8B5CF6,
        )
        embed.add_field(name="Langue actuelle", value=f"**{current}**", inline=False)
        embed.add_field(name="Langues disponibles", value="🇫🇷 **Français**\n🇬🇧 **English**", inline=False)
    embed.set_footer(text=f"SentriX • {_SETUP_BUILD_MARKER}")
    return embed


def _render_language_page(view) -> None:
    view.clear_items()
    english = _is_english(view)
    current = language_runtime.LANG_EN if english else language_runtime.LANG_FR

    fr = discord.ui.Button(
        label="Français",
        emoji="🇫🇷",
        style=discord.ButtonStyle.success if current == language_runtime.LANG_FR else discord.ButtonStyle.secondary,
        custom_id="sentrix:setup:v4:lang:fr",
        row=0,
    )
    en = discord.ui.Button(
        label="English",
        emoji="🇬🇧",
        style=discord.ButtonStyle.success if current == language_runtime.LANG_EN else discord.ButtonStyle.secondary,
        custom_id="sentrix:setup:v4:lang:en",
        row=0,
    )
    home = discord.ui.Button(
        label="Home" if english else "Accueil",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        custom_id="sentrix:setup:v4:lang:home",
        row=1,
    )

    async def choose(interaction: discord.Interaction, choice: str) -> None:
        if not _can_change_language(interaction):
            return await interaction.response.send_message(
                "Administrator permission required. / Permission Administrateur requise.",
                ephemeral=True,
            )
        await language_runtime.set_language(view.bot, view.guild_id, choice)
        view.page = -1
        try:
            await view.persist_session()
        except Exception:
            logger.debug("Session +setup non persistée après changement de langue.", exc_info=True)
        view.render_page()
        await interaction.response.edit_message(embed=await view.build_embed(), view=view)

    async def choose_fr(interaction: discord.Interaction) -> None:
        await choose(interaction, language_runtime.LANG_FR)

    async def choose_en(interaction: discord.Interaction) -> None:
        await choose(interaction, language_runtime.LANG_EN)

    async def go_home(interaction: discord.Interaction) -> None:
        view.page = -1
        view.render_page()
        await interaction.response.edit_message(embed=await view.build_embed(), view=view)

    fr.callback = choose_fr
    en.callback = choose_en
    home.callback = go_home
    view.add_item(fr)
    view.add_item(en)
    view.add_item(home)


def _install_local_slash_cleanup(bot: commands.Bot) -> None:
    """Supprime au démarrage les copies *guild-scoped* créées par l'ancien +syncguild.

    Les vraies commandes SentriX sont globales. Garder en plus une copie locale fait
    apparaître deux /setup (et potentiellement deux exemplaires de beaucoup d'autres
    commandes) dans le sélecteur Discord.
    """
    if getattr(bot, "_sentrix_local_slash_cleanup_listener", False):
        return

    async def cleanup_local_slash_commands() -> None:
        if getattr(bot, "_sentrix_local_slash_cleanup_done", False):
            return
        bot._sentrix_local_slash_cleanup_done = True
        total_removed = 0
        for guild in list(bot.guilds):
            try:
                local_commands = await bot.tree.fetch_commands(guild=guild)
            except discord.HTTPException:
                logger.warning("Impossible de lire les commandes slash locales de %s (%s).", guild.name, guild.id)
                continue
            if not local_commands:
                continue
            try:
                bot.tree.clear_commands(guild=guild)
                await bot.tree.sync(guild=guild)
                total_removed += len(local_commands)
                logger.warning(
                    "Nettoyage slash local : %s ancienne(s) commande(s) supprimée(s) de %s (%s).",
                    len(local_commands), guild.name, guild.id,
                )
            except discord.HTTPException:
                logger.exception("Impossible de supprimer les anciennes commandes slash locales de %s.", guild.id)
        logger.info("Nettoyage slash local terminé : %s ancienne(s) commande(s) supprimée(s).", total_removed)

    bot.add_listener(cleanup_local_slash_commands, "on_ready")
    bot._sentrix_local_slash_cleanup_listener = True


def _patch_syncguild(bot: commands.Bot) -> None:
    """Empêche +syncguild de recréer les doublons global + serveur."""
    command = bot.get_command("syncguild")
    if command is None or getattr(command, "_sentrix_no_local_copy", False):
        return

    async def safe_syncguild(cog, ctx: commands.Context):
        if not ctx.guild:
            return await ctx.send(embed=embeds.error("Cette commande doit être utilisée dans un serveur."))
        try:
            existing = await bot.tree.fetch_commands(guild=ctx.guild)
            bot.tree.clear_commands(guild=ctx.guild)
            await bot.tree.sync(guild=ctx.guild)
            await bot.tree.sync()
        except discord.HTTPException as exc:
            return await ctx.send(embed=embeds.error(f"Discord a refusé la synchronisation : `{exc}`"))

        await ctx.send(embed=embeds.success(
            f"Synchronisation terminée. **{len(existing)}** ancienne(s) commande(s) locale(s) "
            "ont été supprimée(s). SentriX utilise maintenant uniquement les commandes slash globales, "
            "ce qui évite les doublons comme `/setup` affiché deux fois."
        ))

    command.callback = safe_syncguild
    command.description = "Nettoyer les anciennes copies slash locales et resynchroniser les commandes globales."
    command._sentrix_no_local_copy = True
    logger.info("+syncguild sécurisé : aucune copie locale des commandes globales ne sera recréée.")


def install(bot: commands.Bot) -> None:
    # Ces deux garde-fous doivent pouvoir s'installer même avant Configuration.
    _install_local_slash_cleanup(bot)
    _patch_syncguild(bot)

    try:
        from . import configuration
    except Exception:
        return

    if bot.get_cog("Configuration") is None:
        return

    view_cls = getattr(configuration, "SetupView", None)
    config_cls = getattr(configuration, "Configuration", None)
    if view_cls is None or config_cls is None:
        return

    # Une installation v4 par processus. Les anciens marqueurs v1/v2/v3 sont ignorés :
    # ils ne doivent plus pouvoir bloquer cette version.
    if getattr(view_cls, "_sentrix_setup_v4", False):
        return

    current_render_page = view_cls.render_page
    current_build_embed = view_cls.build_embed
    current_open_setup = config_cls._open_setup_panel

    def render_home(self) -> None:
        self.clear_items()
        english = _is_english(self)

        options = [
            discord.SelectOption(
                label="Server language" if english else "Langue du serveur",
                value=LANGUAGE_CATEGORY_VALUE,
                description=(
                    "Switch the whole SentriX interface between English and French"
                    if english else
                    "Passer toute l'interface SentriX en français ou en anglais"
                ),
                emoji="🌐",
            )
        ]

        for index, step in enumerate(configuration.SETUP_STEPS):
            if step.get("key") == "summary":
                continue
            title, summary = _step_meta(step)
            if english:
                title = language_runtime._english_setup_text(title) or title
                summary = language_runtime._english_setup_text(summary) or summary
            options.append(discord.SelectOption(
                label=title[:100],
                value=str(index),
                description=summary[:100],
                emoji=str(step.get("icon") or "⚙️"),
            ))

        category_select = discord.ui.Select(
            placeholder=(
                "Choose what you want to configure…"
                if english else
                "Choisis ce que tu veux configurer…"
            ),
            options=options[:25],
            row=0,
            custom_id="sentrix:setup:v4:category",
        )

        async def category_callback(interaction: discord.Interaction) -> None:
            if not category_select.values:
                return await interaction.response.defer()
            selected = category_select.values[0]
            if selected == LANGUAGE_CATEGORY_VALUE:
                self.page = LANGUAGE_PAGE
            else:
                try:
                    self.page = int(selected)
                except (TypeError, ValueError):
                    return await interaction.response.send_message(
                        "Invalid category. / Catégorie invalide.", ephemeral=True
                    )
            self.render_page()
            try:
                await self.persist_session()
            except Exception:
                logger.debug("Session +setup non persistée après navigation.", exc_info=True)
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)

        category_select.callback = category_callback
        self.add_item(category_select)

        self.add_item(configuration.SetupNavButton(
            "summary", self.message_id,
            label="📋 Summary" if english else "📋 Résumé",
            style=discord.ButtonStyle.primary,
            row=1,
        ))
        self.add_item(configuration.SetupNavButton(
            "history", self.message_id,
            label="📜 History" if english else "📜 Historique",
            style=discord.ButtonStyle.secondary,
            row=1,
        ))
        self.add_item(configuration.SetupNavButton(
            "cancel", self.message_id,
            label="Close" if english else "Fermer",
            style=discord.ButtonStyle.danger,
            row=1,
        ))

        dashboard_url = os.getenv(
            "DASHBOARD_PUBLIC_URL",
            "https://mon-bot-discord-production-8944.up.railway.app",
        ).strip().rstrip("/")
        if dashboard_url.startswith(("https://", "http://")):
            self.add_item(discord.ui.Button(
                label="Open web dashboard" if english else "Ouvrir le dashboard web",
                emoji="🌐",
                style=discord.ButtonStyle.link,
                url=f"{dashboard_url}/app?guild={self.guild_id}&tab=overview",
                row=2,
            ))

    def render_page(self) -> None:
        if getattr(self, "page", None) == -1:
            render_home(self)
            return
        if getattr(self, "page", None) == LANGUAGE_PAGE:
            _render_language_page(self)
            return
        current_render_page(self)

    async def build_embed(self) -> discord.Embed:
        if getattr(self, "page", None) == LANGUAGE_PAGE:
            return _language_embed(self)

        embed = await current_build_embed(self)
        english = _is_english(self)
        if english:
            try:
                language_runtime._translate_setup_embed(embed)
            except Exception:
                logger.debug("Traduction du panneau +setup impossible.", exc_info=True)

        if getattr(self, "page", None) == -1:
            for index in range(len(embed.fields) - 1, -1, -1):
                name = str(embed.fields[index].name or "").strip()
                if name in {"🌐 Langue", "🌐 Language"}:
                    embed.remove_field(index)
            footer = str(embed.footer.text or "").strip() if embed.footer else ""
            if _SETUP_BUILD_MARKER not in footer:
                footer = f"{footer} • {_SETUP_BUILD_MARKER}" if footer else f"SentriX • {_SETUP_BUILD_MARKER}"
                embed.set_footer(text=footer)
        return embed

    async def open_setup_panel(self, *args, **kwargs):
        """Réapplique explicitement le rendu v4 au message réellement envoyé à Discord."""
        result = await current_open_setup(self, *args, **kwargs)
        try:
            message, view = result
            view.page = -1
            view.render_page()
            await message.edit(embed=await view.build_embed(), view=view)
        except Exception:
            logger.exception("Impossible de forcer le rendu +setup v4 après création du panneau.")
        return result

    view_cls._render_home = render_home
    view_cls.render_page = render_page
    view_cls.build_embed = build_embed
    view_cls._sentrix_language_patch = True
    view_cls._sentrix_language_payload_guard = True
    view_cls._sentrix_native_language = True
    view_cls._sentrix_setup_v4 = True

    if not getattr(config_cls._open_setup_panel, "_sentrix_setup_v4", False):
        open_setup_panel._sentrix_setup_v4 = True
        config_cls._open_setup_panel = open_setup_panel

    logger.info(
        "+setup v4 ACTIF : 🌐 Langue/Language est la première catégorie et le panneau final est réédité après création."
    )
