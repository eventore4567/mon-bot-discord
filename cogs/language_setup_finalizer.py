"""Setup V5 autonome + nettoyage fiable des anciennes commandes slash locales.

La V5 ne modifie plus plusieurs méthodes du même SetupView une par une. Elle remplace
l'ancienne classe par une sous-classe unique utilisée directement par Configuration.
Le retour Accueil, les restaurations de session et les nouveaux panneaux passent donc
tous par le même rendu.
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
_SETUP_BUILD_MARKER = "Interface setup v5"


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
    """Supprime les commandes guild-scoped historiques sans toucher aux globales."""
    try:
        remote = await bot.tree.fetch_commands(guild=guild)
    except discord.HTTPException:
        logger.warning("Impossible de lire les commandes slash locales de %s (%s).", guild.name, guild.id)
        return 0

    if not remote:
        return 0

    try:
        bot.tree.clear_commands(guild=guild)
        await bot.tree.sync(guild=guild)
    except discord.HTTPException:
        logger.exception("Impossible de supprimer les commandes slash locales de %s (%s).", guild.name, guild.id)
        return 0

    logger.warning(
        "Nettoyage slash local : %s commande(s) supprimée(s) de %s (%s).",
        len(remote), guild.name, guild.id,
    )
    return len(remote)


def _install_local_slash_cleanup(bot: commands.Bot) -> None:
    """Nettoie les anciens doublons /setup au ready, avec une seconde passe courte."""
    if getattr(bot, "_sentrix_local_slash_cleanup_listener_v5", False):
        return

    async def cleanup_local_slash_commands() -> None:
        if getattr(bot, "_sentrix_local_slash_cleanup_running", False):
            return
        bot._sentrix_local_slash_cleanup_running = True
        try:
            total = 0
            for delay in (0, 8):
                if delay:
                    await asyncio.sleep(delay)
                for guild in list(bot.guilds):
                    total += await _purge_local_slash_for_guild(bot, guild)
            logger.info("Nettoyage slash local V5 terminé : %s commande(s) supprimée(s).", total)
        finally:
            bot._sentrix_local_slash_cleanup_running = False

    bot.add_listener(cleanup_local_slash_commands, "on_ready")
    bot._sentrix_local_slash_cleanup_listener_v5 = True


def _patch_syncguild(bot: commands.Bot) -> None:
    """Transforme +syncguild en outil de nettoyage, sans recréer de copie locale."""
    command = bot.get_command("syncguild")
    if command is None or getattr(command, "_sentrix_no_local_copy_v5", False):
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
            "SentriX utilise désormais uniquement ses commandes slash globales, donc aucun doublon `/setup`."
        ))

    command.callback = safe_syncguild
    command.description = "Nettoyer les anciennes commandes slash locales et resynchroniser SentriX."
    command._sentrix_no_local_copy_v5 = True
    logger.info("+syncguild V5 actif : aucune copie locale ne sera recréée.")


def install(bot: commands.Bot) -> None:
    _install_local_slash_cleanup(bot)
    _patch_syncguild(bot)

    try:
        from . import configuration
    except Exception:
        return

    if bot.get_cog("Configuration") is None:
        return

    base_view_cls = getattr(configuration, "SetupView", None)
    config_cls = getattr(configuration, "Configuration", None)
    if base_view_cls is None or config_cls is None:
        return

    if getattr(base_view_cls, "_sentrix_setup_v5", False):
        return

    class SetupViewV5(base_view_cls):
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
                    if english else
                    "Choisir Français ou English pour ce serveur"
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
                    label=title[:100],
                    value=str(index),
                    description=summary[:100],
                    emoji=str(step.get("icon") or "⚙️"),
                ))

            category_select = discord.ui.Select(
                placeholder=(
                    "Choose a category to configure"
                    if english else
                    "Choisis une catégorie à configurer"
                ),
                options=options[:25],
                row=0,
                custom_id="sentrix:setup:v5:category",
            )
            category_select.callback = self._v5_category_callback(category_select)
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
                    label="Web dashboard" if english else "Dashboard web",
                    emoji="🌐",
                    style=discord.ButtonStyle.link,
                    url=f"{dashboard_url}/app?guild={self.guild_id}&tab=overview",
                    row=2,
                ))

        def _v5_category_callback(self, select: discord.ui.Select):
            async def callback(interaction: discord.Interaction) -> None:
                if not select.values:
                    return await interaction.response.defer()
                selected = select.values[0]
                if selected == LANGUAGE_CATEGORY_VALUE:
                    self.page = LANGUAGE_PAGE
                else:
                    try:
                        self.page = int(selected)
                    except (TypeError, ValueError):
                        return await interaction.response.send_message(
                            "Catégorie invalide. / Invalid category.", ephemeral=True
                        )
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
                custom_id="sentrix:setup:lang:fr", row=0,
            )
            en = discord.ui.Button(
                label="English", emoji="🇬🇧",
                style=discord.ButtonStyle.success if current == language_runtime.LANG_EN else discord.ButtonStyle.secondary,
                custom_id="sentrix:setup:lang:en", row=0,
            )
            home = discord.ui.Button(
                label="Home" if english else "Accueil", emoji="🏠",
                style=discord.ButtonStyle.secondary,
                custom_id="sentrix:setup:lang:home", row=1,
            )

            async def choose(interaction: discord.Interaction, choice: str) -> None:
                if not _can_change_language(interaction):
                    return await interaction.response.send_message(
                        "Permission Administrateur requise. / Administrator permission required.",
                        ephemeral=True,
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

        async def _build_v5_home_embed(self) -> discord.Embed:
            english = _is_english(self)
            guild = self._guild()
            conf = await self.bot.db.get_guild_config(self.guild_id)
            status_rows = await self._compute_categories(conf)
            statuses = [status for _name, status in status_rows]
            configured = 1 + sum(1 for status in statuses if status == "Configuré")
            total = 1 + len(statuses)
            critical = sum(1 for status in statuses if status == "Non configuré")
            warnings = sum(1 for status in statuses if status == "Partiel")
            current_language = "English" if english else "Français"

            if english:
                description = (
                    "Everything important is grouped here. Choose a category below; changes are saved "
                    "without forcing you through a long wizard."
                )
                overall = "Needs attention" if critical else ("Partially configured" if warnings else "Ready")
                embed = discord.Embed(title="⚙️ SENTRIX CONTROL CENTER", description=description, color=0x8B5CF6)
                embed.add_field(name="Server", value=guild.name if guild else "Unknown", inline=True)
                embed.add_field(name="Configured", value=f"{configured}/{total}", inline=True)
                embed.add_field(name="Status", value=overall, inline=True)
                lines = [f"🌐 **Server language** · {current_language}"]
            else:
                description = (
                    "Tous les réglages importants sont regroupés ici. Choisis une catégorie ci-dessous : "
                    "aucun parcours forcé, tu vas directement à ce que tu veux modifier."
                )
                overall = "À vérifier" if critical else ("Configuration partielle" if warnings else "Prêt")
                embed = discord.Embed(title="⚙️ CENTRE DE CONTRÔLE SENTRIX", description=description, color=0x8B5CF6)
                embed.add_field(name="Serveur", value=guild.name if guild else "Inconnu", inline=True)
                embed.add_field(name="Configuré", value=f"{configured}/{total}", inline=True)
                embed.add_field(name="État", value=overall, inline=True)
                lines = [f"🌐 **Langue du serveur** · {current_language}"]

            visible_steps = [step for step in configuration.SETUP_STEPS if step.get("key") != "summary"]
            for index, step in enumerate(visible_steps):
                title, _summary = _step_meta(step)
                if english:
                    title = language_runtime._english_setup_text(title) or title
                status = statuses[index] if index < len(statuses) else "Partiel"
                lines.append(f"{step.get('icon', '•')} **{title}** · {_status_text(status, english)}")

            embed.add_field(
                name="Categories" if english else "Catégories",
                value="\n".join(lines)[:1024],
                inline=False,
            )
            embed.add_field(
                name="Quick access" if english else "Accès rapide",
                value=(
                    "Use the menu above, then **Summary** to review everything before closing."
                    if english else
                    "Utilise le menu au-dessus, puis **Résumé** pour vérifier l'ensemble avant de fermer."
                ),
                inline=False,
            )
            embed.set_footer(text=f"SentriX • {_SETUP_BUILD_MARKER}")
            return embed

        async def _build_language_embed(self) -> discord.Embed:
            english = _is_english(self)
            current = "English" if english else "Français"
            if english:
                embed = discord.Embed(
                    title="🌐 Server language",
                    description="Choose the language used by SentriX on this server.",
                    color=0x8B5CF6,
                )
                embed.add_field(name="Current", value=f"**{current}**", inline=False)
                embed.add_field(name="Available", value="🇫🇷 Français\n🇬🇧 English", inline=False)
            else:
                embed = discord.Embed(
                    title="🌐 Langue du serveur",
                    description="Choisis la langue utilisée par SentriX sur ce serveur.",
                    color=0x8B5CF6,
                )
                embed.add_field(name="Actuelle", value=f"**{current}**", inline=False)
                embed.add_field(name="Disponibles", value="🇫🇷 Français\n🇬🇧 English", inline=False)
            embed.set_footer(text=f"SentriX • {_SETUP_BUILD_MARKER}")
            return embed

        async def build_embed(self) -> discord.Embed:
            if getattr(self, "page", -1) == -1:
                return await self._build_v5_home_embed()
            if getattr(self, "page", -1) == LANGUAGE_PAGE:
                return await self._build_language_embed()
            embed = await super().build_embed()
            if _is_english(self):
                try:
                    language_runtime._translate_setup_embed(embed)
                except Exception:
                    logger.debug("Traduction de la page +setup impossible.", exc_info=True)
            return embed

    # Le symbole global lu par Configuration._open_setup_panel et par la restauration des
    # sessions pointe désormais vers la V5. Aucun wrapper de render_page n'est nécessaire.
    configuration.SetupView = SetupViewV5

    current_open_setup = config_cls._open_setup_panel
    if not getattr(current_open_setup, "_sentrix_setup_v5", False):
        async def open_setup_panel_v5(self, ctx_or_channel, *args, **kwargs):
            guild = getattr(ctx_or_channel, "guild", None)
            if guild is not None:
                # Nettoyage immédiat : le simple fait d'ouvrir +setup supprime aussi les
                # vieilles copies guild-scoped responsables des deux /setup dans Discord.
                try:
                    await _purge_local_slash_for_guild(self.bot, guild)
                except Exception:
                    logger.exception("Nettoyage slash local impossible pendant l'ouverture de +setup.")
            return await current_open_setup(self, ctx_or_channel, *args, **kwargs)

        open_setup_panel_v5._sentrix_setup_v5 = True
        config_cls._open_setup_panel = open_setup_panel_v5

    logger.info(
        "+setup V5 NATIF actif : nouvelle classe SetupView, langue en première catégorie et nettoyage slash automatique."
    )
