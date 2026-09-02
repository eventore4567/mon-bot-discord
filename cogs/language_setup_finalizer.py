"""Finaliseur de langue pour le Setup SentriX.

Cette couche ne remplace plus le design du Setup. Elle ajoute uniquement le choix de
langue au centre de configuration déjà stylé par setup_oxyde_style, puis délègue toutes
les pages normales à cette interface. Les anciennes cartes V6 avec progression, liste de
modules, historique et dashboard ne sont volontairement plus reconstruites ici.
"""
from __future__ import annotations

import asyncio
import logging
import re
import types

import discord
from discord.ext import commands

from utils import embeds
from utils import sentrix_panels as panels
from . import language_runtime

logger = logging.getLogger("bot.language-setup-finalizer")

LANGUAGE_CATEGORY_VALUE = "__sentrix_language__"
LANGUAGE_PAGE = -20260809
_SETUP_COLOR = 0x6C5CE7
_EMOJI_RE = re.compile(
    r"<a?:[A-Za-z0-9_]+:\d+>|"
    r"[\U0001F1E6-\U0001F1FF\U0001F300-\U0001FAFF\u2300-\u23FF\u2600-\u27BF\uFE0F\u200D]"
)


def _clean_text(value: object) -> str:
    text = str(value or "")
    text = _EMOJI_RE.sub("", text)
    return " ".join(text.split()).strip()


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
    title = _clean_text(meta.get("title") or step.get("title") or step.get("key") or "Configuration")
    summary = _clean_text(meta.get("summary") or step.get("description") or "Configurer ce module.")
    return title or "Configuration", summary or "Configurer ce module."


def _avatar_url(bot: commands.Bot) -> str | None:
    try:
        return str(bot.user.display_avatar.url) if bot.user else None
    except Exception:
        return None


def _set_author(embed: discord.Embed, bot: commands.Bot) -> None:
    icon = _avatar_url(bot)
    if icon:
        embed.set_author(name="SentriX", icon_url=icon)
    else:
        embed.set_author(name="SentriX")


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
            logger.info("Nettoyage slash terminé : %s commande(s) locale(s) supprimée(s).", total)
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
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Cette commande doit être utilisée dans un serveur.')))
        removed = await _purge_local_slash_for_guild(bot, ctx.guild)
        try:
            await bot.tree.sync()
        except discord.HTTPException as exc:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'Discord a refusé la synchronisation globale : `{exc}`')))
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Synchronisation terminée. **{removed}** ancienne(s) commande(s) locale(s) supprimée(s). SentriX utilise uniquement ses commandes slash globales.')))

    command.callback = safe_syncguild
    command.description = "Nettoyer les anciens slash locaux et resynchroniser SentriX."
    command._sentrix_no_local_copy_v6 = True


def _bind_live_opener(config_cog, config_cls, direct_open) -> None:
    config_cls._open_setup_panel = direct_open
    config_cog._open_setup_panel = types.MethodType(direct_open, config_cog)
    config_cog._sentrix_setup_v6_bound = True


def install(bot: commands.Bot) -> None:
    _install_local_slash_cleanup(bot)
    _patch_syncguild(bot)

    try:
        from . import configuration
    except Exception:
        return

    config_cls = getattr(configuration, "Configuration", None)
    base_view_cls = getattr(configuration, "SetupView", None)
    config_cog = bot.get_cog("Configuration")
    if config_cog is None or config_cls is None or base_view_cls is None:
        return

    if getattr(base_view_cls, "_sentrix_setup_v6", False):
        direct_open = getattr(config_cls, "_sentrix_open_setup_panel_v6", None)
        if direct_open is not None:
            _bind_live_opener(config_cog, config_cls, direct_open)
        return

    class SetupViewV6(base_view_cls):
        """Ajoute la page Langue sans remplacer le rendu compact du Setup principal."""

        _sentrix_setup_v6 = True
        _sentrix_setup_v7_clean = True
        _sentrix_setup_v5 = True
        _sentrix_setup_v4 = True
        _sentrix_native_language = True
        _sentrix_language_patch = True
        _sentrix_language_payload_guard = True
        _sentrix_setup_compact_final = True

        def _render_home(self) -> None:
            self.clear_items()
            english = _is_english(self)
            options: list[discord.SelectOption] = [
                discord.SelectOption(
                    label="Server language" if english else "Langue du serveur",
                    value=LANGUAGE_CATEGORY_VALUE,
                    description=(
                        "Choose the language used by SentriX"
                        if english else "Choisir la langue utilisée par SentriX"
                    ),
                    emoji="🌐",
                )
            ]

            for index, step in enumerate(configuration.SETUP_STEPS):
                if step.get("key") == "summary":
                    continue
                title, summary = _step_meta(step)
                if english:
                    title = _clean_text(language_runtime._english_setup_text(title) or title)
                    summary = _clean_text(language_runtime._english_setup_text(summary) or summary)
                options.append(discord.SelectOption(
                    label=title[:100],
                    value=str(index),
                    description=summary[:100],
                    emoji=step.get("icon") or None,
                ))

            selector = discord.ui.Select(
                placeholder="Choose what you want to configure…" if english else 'Choisissez ce que vous voulez configurer…',
                options=options[:25],
                min_values=1,
                max_values=1,
                row=0,
                custom_id="sentrix:setup:v6:category",
            )
            selector.callback = self._v6_category_callback(selector)
            self.add_item(selector)
            self.add_item(configuration.SetupNavButton(
                "cancel",
                self.message_id,
                label="Close" if english else "Fermer",
                style=discord.ButtonStyle.secondary,
                row=1,
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
                await panels.editer(interaction.response, panels.avec_composants(panels.depuis_embed(await self.build_embed()), self))
            return callback

        def _render_language_page(self) -> None:
            self.clear_items()
            english = _is_english(self)
            current = language_runtime.LANG_EN if english else language_runtime.LANG_FR

            fr = discord.ui.Button(
                label="Français",
                style=discord.ButtonStyle.primary if current == language_runtime.LANG_FR else discord.ButtonStyle.secondary,
                custom_id="sentrix:setup:v6:lang:fr",
                row=0,
            )
            en = discord.ui.Button(
                label="English",
                style=discord.ButtonStyle.primary if current == language_runtime.LANG_EN else discord.ButtonStyle.secondary,
                custom_id="sentrix:setup:v6:lang:en",
                row=0,
            )
            home = discord.ui.Button(
                label="Home" if english else "Accueil",
                style=discord.ButtonStyle.secondary,
                custom_id="sentrix:setup:v6:lang:home",
                row=1,
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
                await panels.editer(interaction.response, panels.avec_composants(panels.depuis_embed(await self.build_embed()), self))

            async def choose_fr(interaction: discord.Interaction) -> None:
                await choose(interaction, language_runtime.LANG_FR)

            async def choose_en(interaction: discord.Interaction) -> None:
                await choose(interaction, language_runtime.LANG_EN)

            async def go_home(interaction: discord.Interaction) -> None:
                self.page = -1
                self.render_page()
                await panels.editer(interaction.response, panels.avec_composants(panels.depuis_embed(await self.build_embed()), self))

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
            # Important : le design vient du Setup compact installé juste avant cette
            # couche. On ne le reconstruit plus ici.
            super().render_page()

        async def _build_home_embed_v6(self) -> discord.Embed:
            english = _is_english(self)
            guild = self._guild()
            embed = discord.Embed(
                title="SentriX • Configuration",
                description=(
                    "Choose a category below to configure SentriX for this server."
                    if english else
                    'Choisissez une catégorie ci-dessous pour configurer SentriX sur ce serveur.'
                ),
                color=_SETUP_COLOR,
            )
            _set_author(embed, self.bot)
            embed.set_footer(text=f"SentriX • {guild.name if guild else 'Serveur'}")
            return embed

        async def _build_language_embed_v6(self) -> discord.Embed:
            english = _is_english(self)
            guild = self._guild()
            embed = discord.Embed(
                title="SentriX • Language" if english else "SentriX • Langue",
                description=(
                    "Choose the language used by SentriX on this server."
                    if english else
                    'Choisissez la langue utilisée par SentriX sur ce serveur.'
                ),
                color=_SETUP_COLOR,
            )
            _set_author(embed, self.bot)
            embed.set_footer(text=f"SentriX • {guild.name if guild else 'Serveur'}")
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

    configuration.SetupView = SetupViewV6

    async def open_setup_panel_v6(self, ctx_or_channel, *, author: discord.Member = None):
        guild = getattr(ctx_or_channel, "guild", None)
        if guild is None:
            raise RuntimeError("+setup doit être utilisé dans un serveur Discord")
        author = author or getattr(ctx_or_channel, "author", None)
        if author is None:
            raise RuntimeError("Auteur +setup introuvable")
        channel = getattr(ctx_or_channel, "channel", None)
        channel_id = channel.id if channel is not None else ctx_or_channel.id

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
            title="SentriX • Configuration",
            description="Ouverture…",
            color=_SETUP_COLOR,
        )
        message = await panels.envoyer(ctx_or_channel, panels.depuis_embed(placeholder))
        view = SetupViewV6(
            self.bot,
            guild.id,
            author.id,
            message.id,
            channel_id,
            existing_managers=existing_managers,
            existing_security=existing_security,
            existing_exempt_roles=existing_exempt,
        )
        self.active_setups[message.id] = view
        self.active_by_guild[guild.id] = (message.id, author.id, str(author))
        await view.persist_session()
        await panels.editer(message, panels.avec_composants(panels.depuis_embed(await view.build_embed()), view))

        asyncio.create_task(
            _purge_local_slash_for_guild(self.bot, guild),
            name=f"sentrix-slash-clean-{guild.id}",
        )
        return message, view

    open_setup_panel_v6._sentrix_setup_v6 = True
    config_cls._sentrix_open_setup_panel_v6 = open_setup_panel_v6
    _bind_live_opener(config_cog, config_cls, open_setup_panel_v6)

    logger.info("+setup final : interface compacte conservée et langue ajoutée sans ancien dashboard.")
