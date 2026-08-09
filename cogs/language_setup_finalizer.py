"""Setup V6 : panneau direct, langue native et nettoyage des anciens slash locaux.

La V6 ne repasse plus par l'ancien _open_setup_panel. Le message envoyé par +setup est
construit directement avec SetupViewV6, ce qui garantit que la catégorie Langue est
présente même si une ancienne couche visuelle a conservé une référence au vieux renderer.
"""
from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord.ext import commands

from utils import embeds
from . import language_runtime

logger = logging.getLogger("bot.language-setup-finalizer")

LANGUAGE_CATEGORY_VALUE = "__sentrix_language__"
LANGUAGE_PAGE = -20260809
_SETUP_BUILD_MARKER = "Interface setup v6"


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


def _status_text(value: str, english: bool) -> str:
    if not english:
        return value
    return {
        "Configuré": "Configured",
        "Partiel": "Partial",
        "Non configuré": "Not configured",
    }.get(value, value)


async def _purge_local_slash_for_guild(bot: commands.Bot, guild: discord.Guild) -> int:
    try:
        remote = await bot.tree.fetch_commands(guild=guild)
    except discord.HTTPException:
        logger.warning("Impossible de lire les slash locaux de %s (%s).", guild.name, guild.id)
        return 0
    if not remote:
        return 0
    try:
        bot.tree.clear_commands(guild=guild)
        await bot.tree.sync(guild=guild)
    except discord.HTTPException:
        logger.exception("Impossible de supprimer les slash locaux de %s (%s).", guild.name, guild.id)
        return 0
    logger.warning("Nettoyage slash local : %s commande(s) supprimée(s) de %s.", len(remote), guild.id)
    return len(remote)


def _install_local_slash_cleanup(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_local_slash_cleanup_listener_v6", False):
        return

    async def cleanup() -> None:
        if getattr(bot, "_sentrix_local_slash_cleanup_running_v6", False):
            return
        bot._sentrix_local_slash_cleanup_running_v6 = True
        try:
            total = 0
            for delay in (0, 8):
                if delay:
                    await asyncio.sleep(delay)
                for guild in list(bot.guilds):
                    total += await _purge_local_slash_for_guild(bot, guild)
            logger.info("Nettoyage slash V6 terminé : %s commande(s) locale(s) supprimée(s).", total)
        finally:
            bot._sentrix_local_slash_cleanup_running_v6 = False

    bot.add_listener(cleanup, "on_ready")
    bot._sentrix_local_slash_cleanup_listener_v6 = True


def _patch_syncguild(bot: commands.Bot) -> None:
    command = bot.get_command("syncguild")
    if command is None or getattr(command, "_sentrix_no_local_copy_v6", False):
        return

    async def safe_syncguild(cog, ctx: commands.Context):
        if not ctx.guild:
            return await ctx.send(embed=embeds.error("Cette commande doit être utilisée dans un serveur."))
        removed = await _purge_local_slash_for_guild(bot, ctx.guild)
        try:
            await bot.tree.sync()
        except discord.HTTPException as exc:
            return await ctx.send(embed=embeds.error(f"Discord a refusé la synchronisation globale : `{exc}`"))
        await ctx.send(embed=embeds.success(
            f"Synchronisation terminée. **{removed}** ancienne(s) commande(s) locale(s) supprimée(s). "
            "SentriX utilise uniquement ses commandes slash globales."
        ))

    command.callback = safe_syncguild
    command.description = "Nettoyer les anciens slash locaux et resynchroniser SentriX."
    command._sentrix_no_local_copy_v6 = True


def install(bot: commands.Bot) -> None:
    _install_local_slash_cleanup(bot)
    _patch_syncguild(bot)

    try:
        from . import configuration
    except Exception:
        return

    config_cls = getattr(configuration, "Configuration", None)
    base_view_cls = getattr(configuration, "SetupView", None)
    if bot.get_cog("Configuration") is None or config_cls is None or base_view_cls is None:
        return
    if getattr(base_view_cls, "_sentrix_setup_v6", False):
        return

    class SetupViewV6(base_view_cls):
        _sentrix_setup_v6 = True
        _sentrix_setup_v5 = True
        _sentrix_setup_v4 = True
        _sentrix_native_language = True
        _sentrix_language_patch = True
        _sentrix_language_payload_guard = True

        def _render_home(self) -> None:
            self.clear_items()
            english = _is_english(self)
            options = [discord.SelectOption(
                label="Server language" if english else "Langue du serveur",
                value=LANGUAGE_CATEGORY_VALUE,
                description=(
                    "Switch SentriX between English and French"
                    if english else "Choisir Français ou English pour ce serveur"
                ),
                emoji="🌐",
            )]
            for index, step in enumerate(configuration.SETUP_STEPS):
                if step.get("key") == "summary":
                    continue
                title, summary = _step_meta(step)
                if english:
                    title = language_runtime._english_setup_text(title) or title
                    summary = language_runtime._english_setup_text(summary) or summary
                options.append(discord.SelectOption(
                    label=title[:100], value=str(index), description=summary[:100],
                    emoji=str(step.get("icon") or "⚙️"),
                ))

            selector = discord.ui.Select(
                placeholder="Choose a category to configure" if english else "Choisis une catégorie à configurer",
                options=options[:25], row=0, custom_id="sentrix:setup:v6:category",
            )
            selector.callback = self._v6_category_callback(selector)
            self.add_item(selector)
            self.add_item(configuration.SetupNavButton(
                "summary", self.message_id, label="📋 Summary" if english else "📋 Résumé",
                style=discord.ButtonStyle.primary, row=1,
            ))
            self.add_item(configuration.SetupNavButton(
                "history", self.message_id, label="📜 History" if english else "📜 Historique",
                style=discord.ButtonStyle.secondary, row=1,
            ))
            self.add_item(configuration.SetupNavButton(
                "cancel", self.message_id, label="Close" if english else "Fermer",
                style=discord.ButtonStyle.danger, row=1,
            ))

            dashboard_url = os.getenv(
                "DASHBOARD_PUBLIC_URL", "https://mon-bot-discord-production-8944.up.railway.app"
            ).strip().rstrip("/")
            if dashboard_url.startswith(("https://", "http://")):
                self.add_item(discord.ui.Button(
                    label="Web dashboard" if english else "Dashboard web", emoji="🌐",
                    style=discord.ButtonStyle.link,
                    url=f"{dashboard_url}/app?guild={self.guild_id}&tab=overview", row=2,
                ))

        def _v6_category_callback(self, selector: discord.ui.Select):
            async def callback(interaction: discord.Interaction) -> None:
                if not selector.values:
                    return await interaction.response.defer()
                value = selector.values[0]
                if value == LANGUAGE_CATEGORY_VALUE:
                    self.page = LANGUAGE_PAGE
                else:
                    try:
                        self.page = int(value)
                    except (TypeError, ValueError):
                        return await interaction.response.send_message("Catégorie invalide.", ephemeral=True)
                self.render_page()
                await self.persist_session()
                await interaction.response.edit_message(embed=await self.build_embed(), view=self)
            return callback

        def _render_language_page(self) -> None:
            self.clear_items()
            english = _is_english(self)
            current = language_runtime.LANG_EN if english else language_runtime.LANG_FR
            fr = discord.ui.Button(
                label="Français", emoji="🇫🇷",
                style=discord.ButtonStyle.success if current == language_runtime.LANG_FR else discord.ButtonStyle.secondary,
                custom_id="sentrix:setup:v6:lang:fr", row=0,
            )
            en = discord.ui.Button(
                label="English", emoji="🇬🇧",
                style=discord.ButtonStyle.success if current == language_runtime.LANG_EN else discord.ButtonStyle.secondary,
                custom_id="sentrix:setup:v6:lang:en", row=0,
            )
            home = discord.ui.Button(
                label="Home" if english else "Accueil", emoji="🏠",
                style=discord.ButtonStyle.secondary, custom_id="sentrix:setup:v6:lang:home", row=1,
            )

            async def choose(interaction: discord.Interaction, choice: str) -> None:
                if not _can_change_language(interaction):
                    return await interaction.response.send_message(
                        "Permission Administrateur requise. / Administrator permission required.", ephemeral=True
                    )
                await language_runtime.set_language(self.bot, self.guild_id, choice)
                self.page = -1
                self.render_page()
                await self.persist_session()
                await interaction.response.edit_message(embed=await self.build_embed(), view=self)

            async def choose_fr(interaction: discord.Interaction) -> None:
                await choose(interaction, language_runtime.LANG_FR)

            async def choose_en(interaction: discord.Interaction) -> None:
                await choose(interaction, language_runtime.LANG_EN)

            async def go_home(interaction: discord.Interaction) -> None:
                self.page = -1
                self.render_page()
                await interaction.response.edit_message(embed=await self.build_embed(), view=self)

            fr.callback = choose_fr
            en.callback = choose_en
            home.callback = go_home
            self.add_item(fr)
            self.add_item(en)
            self.add_item(home)

        def render_page(self) -> None:
            if getattr(self, "page", -1) == -1:
                self._render_home()
                return
            if getattr(self, "page", -1) == LANGUAGE_PAGE:
                self._render_language_page()
                return
            super().render_page()

        async def _build_home_embed_v6(self) -> discord.Embed:
            english = _is_english(self)
            guild = self._guild()
            conf = await self.bot.db.get_guild_config(self.guild_id)
            rows = await self._compute_categories(conf)
            statuses = [status for _name, status in rows]
            configured = 1 + sum(1 for status in statuses if status == "Configuré")
            total = 1 + len(statuses)
            current_language = "English" if english else "Français"

            embed = discord.Embed(
                title="⚙️ SENTRIX CONTROL CENTER" if english else "⚙️ CENTRE DE CONTRÔLE SENTRIX",
                description=(
                    "Choose a category below. The first category lets you change the whole server language."
                    if english else
                    "Choisis une catégorie ci-dessous. La première permet de changer toute la langue du serveur."
                ),
                color=0x8B5CF6,
            )
            embed.add_field(name="Server" if english else "Serveur", value=guild.name if guild else "—", inline=True)
            embed.add_field(name="Configured" if english else "Configuré", value=f"{configured}/{total}", inline=True)
            embed.add_field(name="Language" if english else "Langue", value=current_language, inline=True)

            lines = [f"🌐 **{'Server language' if english else 'Langue du serveur'}** · {current_language}"]
            visible_steps = [s for s in configuration.SETUP_STEPS if s.get("key") != "summary"]
            for index, step in enumerate(visible_steps):
                title, _ = _step_meta(step)
                if english:
                    title = language_runtime._english_setup_text(title) or title
                status = statuses[index] if index < len(statuses) else "Partiel"
                lines.append(f"{step.get('icon', '•')} **{title}** · {_status_text(status, english)}")
            embed.add_field(name="Categories" if english else "Catégories", value="\n".join(lines)[:1024], inline=False)
            embed.set_footer(text=f"SentriX • {_SETUP_BUILD_MARKER}")
            return embed

        async def _build_language_embed_v6(self) -> discord.Embed:
            english = _is_english(self)
            current = "English" if english else "Français"
            embed = discord.Embed(
                title="🌐 Server language" if english else "🌐 Langue du serveur",
                description=(
                    "Choose the language used for SentriX commands, help and main interfaces."
                    if english else
                    "Choisis la langue utilisée pour les commandes, l'aide et les interfaces principales de SentriX."
                ),
                color=0x8B5CF6,
            )
            embed.add_field(name="Current" if english else "Actuelle", value=f"**{current}**", inline=False)
            embed.add_field(name="Available" if english else "Disponibles", value="🇫🇷 Français\n🇬🇧 English", inline=False)
            embed.set_footer(text=f"SentriX • {_SETUP_BUILD_MARKER}")
            return embed

        async def build_embed(self) -> discord.Embed:
            if getattr(self, "page", -1) == -1:
                return await self._build_home_embed_v6()
            if getattr(self, "page", -1) == LANGUAGE_PAGE:
                return await self._build_language_embed_v6()
            embed = await super().build_embed()
            if _is_english(self):
                try:
                    language_runtime._translate_setup_embed(embed)
                except Exception:
                    logger.debug("Traduction d'une page +setup impossible.", exc_info=True)
            return embed

    # Toutes les restaurations de session qui consultent configuration.SetupView utiliseront V6.
    configuration.SetupView = SetupViewV6

    async def open_setup_panel_v6(self, ctx_or_channel, *, author: discord.Member = None):
        """Construit le panneau V6 directement, sans appeler l'ancien _open_setup_panel."""
        guild = getattr(ctx_or_channel, "guild", None)
        if guild is None:
            raise RuntimeError("+setup doit être utilisé dans un serveur Discord")
        author = author or getattr(ctx_or_channel, "author", None)
        if author is None:
            raise RuntimeError("Auteur +setup introuvable")
        channel = getattr(ctx_or_channel, "channel", None)
        channel_id = channel.id if channel is not None else ctx_or_channel.id

        # Charge la langue réelle avant de construire les composants (cached_language est ensuite instantané).
        await language_runtime.get_language(self.bot, guild.id)

        rows = await self.bot.db.list_bot_managers(guild.id)
        existing_managers = {}
        for row in rows:
            member = guild.get_member(row["user_id"])
            existing_managers[row["user_id"]] = member.display_name if member else f"Membre {row['user_id']}"

        automod_conf = await self.bot.db.get_automod(guild.id)
        existing_security = {
            field: (automod_conf[field] if automod_conf else 0)
            for field in configuration.AUTOMOD_TOGGLE_LABELS
        }
        exempt_rows = await self.bot.db.list_automod_exempt_roles(guild.id)
        existing_exempt = [row["role_id"] for row in exempt_rows]

        placeholder = discord.Embed(
            title="⚙️ SentriX • Setup V6",
            description="Chargement du centre de configuration…",
            color=0x8B5CF6,
        )
        message = await ctx_or_channel.send(embed=placeholder)
        view = SetupViewV6(
            self.bot, guild.id, author.id, message.id, channel_id,
            existing_managers=existing_managers,
            existing_security=existing_security,
            existing_exempt_roles=existing_exempt,
        )
        self.active_setups[message.id] = view
        self.active_by_guild[guild.id] = (message.id, author.id, str(author))
        await view.persist_session()
        await message.edit(embed=await view.build_embed(), view=view)

        # Ne ralentit pas l'ouverture du panneau : le nettoyage des anciens slash part en arrière-plan.
        asyncio.create_task(_purge_local_slash_for_guild(self.bot, guild), name=f"sentrix-slash-clean-{guild.id}")
        return message, view

    open_setup_panel_v6._sentrix_setup_v6 = True
    config_cls._open_setup_panel = open_setup_panel_v6

    logger.info(
        "+setup V6 DIRECT actif : _open_setup_panel remplacé, 🌐 Langue première catégorie, renderer historique contourné."
    )
