"""Rendu premium de +setup, au plus proche du panneau OXYDE fourni en référence.

Ce module ne touche qu'à +setup : aucune logique de modération, tickets, logs, sécurité,
permissions ou base de données n'est modifiée. La page d'accueil utilise Components V2
quand discord.py >= 2.6 est disponible ; les pages de réglage existantes restent intactes.
"""

from __future__ import annotations

import io
import logging
import os

import discord
from discord.ext import commands
from PIL import Image, ImageDraw

from utils import embeds

logger = logging.getLogger("bot.setup-premium-style")
_INSTALLED = False

PURPLE_MAIN = 0x8B5CF6
PURPLE_SECONDARY = 0xA855F7
DASHBOARD_FALLBACK = "https://mon-bot-discord-production-8944.up.railway.app"


def _avatar_url(bot: commands.Bot) -> str | None:
    user = getattr(bot, "user", None)
    if not user:
        return None
    try:
        return user.display_avatar.url
    except Exception:
        return None


def _set_author(embed: discord.Embed, bot: commands.Bot) -> None:
    avatar = _avatar_url(bot)
    if avatar:
        embed.set_author(name="SentriX • Configuration", icon_url=avatar)
    else:
        embed.set_author(name="SentriX • Configuration")


def _status_icon(status: str) -> str:
    if status == "Configuré":
        return "🟢"
    if status == "Partiel":
        return "🟡"
    return "⚪"


async def _build_header_file(bot: commands.Bot) -> discord.File | None:
    """Crée le bandeau visible en haut : deux traits violets + logo SentriX centré."""
    user = getattr(bot, "user", None)
    if user is None:
        return None

    try:
        avatar_bytes = await user.display_avatar.with_size(128).read()
        avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        avatar.thumbnail((86, 86), Image.Resampling.LANCZOS)

        width, height = 1000, 124
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        center_x = width // 2
        center_y = height // 2

        # Traits dégradés, très proches de la référence : plus lumineux vers le logo,
        # presque transparents aux extrémités.
        left_start, left_end = 42, center_x - 82
        right_start, right_end = center_x + 82, width - 42
        for x in range(left_start, left_end):
            ratio = (x - left_start) / max(1, left_end - left_start)
            alpha = int(28 + 227 * ratio)
            colour = (151, 67, 255, alpha)
            draw.rectangle((x, center_y - 2, x + 1, center_y + 2), fill=colour)
        for x in range(right_start, right_end):
            ratio = (right_end - x) / max(1, right_end - right_start)
            alpha = int(28 + 227 * ratio)
            colour = (151, 67, 255, alpha)
            draw.rectangle((x, center_y - 2, x + 1, center_y + 2), fill=colour)

        # Petit halo derrière le logo pour retrouver le point focal central de la capture.
        glow = Image.new("RGBA", (110, 110), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        for radius, alpha in ((50, 18), (45, 26), (40, 38)):
            box = (55 - radius, 55 - radius, 55 + radius, 55 + radius)
            glow_draw.ellipse(box, fill=(139, 92, 246, alpha))
        canvas.alpha_composite(glow, (center_x - 55, center_y - 55))

        avatar_x = center_x - avatar.width // 2
        avatar_y = center_y - avatar.height // 2
        canvas.alpha_composite(avatar, (avatar_x, avatar_y))

        output = io.BytesIO()
        canvas.save(output, format="PNG", optimize=True)
        output.seek(0)
        return discord.File(output, filename="sentrix-setup-header.png")
    except Exception:
        logger.exception("Impossible de générer le bandeau avec le logo SentriX.")
        return None


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import configuration

    configuration.SETUP_COLOR_MAIN = PURPLE_MAIN
    configuration.SETUP_COLOR_SECONDARY = PURPLE_SECONDARY

    # ------------------------------------------------------------------
    # Style des pages classiques qui s'ouvrent APRÈS le bouton Configurer.
    # ------------------------------------------------------------------
    original_build_embed = configuration.SetupView.build_embed

    async def build_home_embed(self) -> discord.Embed:
        conf = await self.bot.db.get_guild_config(self.guild_id)
        guild = self._guild()
        categories = await self._compute_categories(conf)
        prefix = conf["prefix"] if conf and conf["prefix"] else "+"

        configured = sum(1 for _, status in categories if status == "Configuré")
        partial = sum(1 for _, status in categories if status == "Partiel")
        missing = sum(1 for _, status in categories if status == "Non configuré")
        if missing:
            global_state = f"⚪ {missing} module(s) à terminer"
        elif partial:
            global_state = f"🟡 {partial} module(s) partiellement configuré(s)"
        else:
            global_state = "🟢 Configuration complète"

        e = discord.Embed(color=PURPLE_MAIN)
        avatar = _avatar_url(self.bot)
        _set_author(e, self.bot)
        e.title = "👋 - Salut, je suis SentriX"
        e.description = (
            f"> Mon préfixe sur ce serveur est **`{prefix}`**\n"
            f"> Pour obtenir la liste des commandes, tape **`{prefix}help`**\n"
            "> 🟣 Je suis aussi disponible en slash commande `/`"
        )
        server_name = guild.name if guild else "Serveur inconnu"
        e.add_field(
            name="Configuration",
            value=f"**{configured}/{len(categories)}** modules prêts • {global_state}",
            inline=False,
        )
        if avatar:
            e.set_thumbnail(url=avatar)
        e.set_footer(text=f"SentriX --- {server_name}")
        return e

    async def build_embed(self) -> discord.Embed:
        if self.page == -1:
            return await build_home_embed(self)

        e = await original_build_embed(self)
        step = configuration.SETUP_STEPS[self.page]
        avatar = _avatar_url(self.bot)
        guild = self._guild()
        e.colour = discord.Colour(PURPLE_MAIN)
        e.title = f"{step['icon']}・{step['title']}"
        _set_author(e, self.bot)
        if avatar:
            e.set_thumbnail(url=avatar)
        e.set_footer(text=f"SentriX --- {guild.name if guild else 'Configuration'}")
        return e

    configuration.SetupView._build_home_embed = build_home_embed
    configuration.SetupView.build_embed = build_embed

    # ------------------------------------------------------------------
    # Devant EXACT de +setup en Components V2.
    # ------------------------------------------------------------------
    supports_v2 = all(
        hasattr(discord.ui, name)
        for name in ("LayoutView", "Container", "TextDisplay", "Separator", "MediaGallery", "ActionRow")
    )

    if supports_v2:
        original_open_setup_panel = configuration.Configuration._open_setup_panel

        class SetupLandingView(discord.ui.LayoutView):
            def __init__(
                self,
                cog: configuration.Configuration,
                *,
                guild: discord.Guild,
                author: discord.Member,
                prefix: str,
                header_file: discord.File | None,
            ):
                super().__init__(timeout=300)
                self.cog = cog
                self.guild_id = guild.id
                self.author_id = author.id
                self.prefix = prefix

                container = discord.ui.Container(accent_colour=discord.Colour(PURPLE_MAIN))

                # Le bandeau est le seul moyen Discord d'avoir réellement le logo du bot
                # CENTRÉ entre deux traits, comme sur la capture de référence.
                if header_file is not None:
                    gallery = discord.ui.MediaGallery()
                    gallery.add_item(media=header_file, description="SentriX")
                    container.add_item(gallery)
                else:
                    container.add_item(discord.ui.TextDisplay("━━━━━━━━━━━━━━  ◈  ━━━━━━━━━━━━━━"))

                container.add_item(
                    discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small)
                )
                container.add_item(
                    discord.ui.TextDisplay("## 👋 - Salut, je suis SentriX")
                )
                container.add_item(
                    discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small)
                )
                container.add_item(
                    discord.ui.TextDisplay(
                        f"> Mon préfixe sur ce serveur est `{prefix}`\n"
                        f"> Pour obtenir la liste des commandes, tapez `{prefix}help`\n"
                        "> 🟣  Je suis aussi disponible en slash commande"
                    )
                )
                container.add_item(
                    discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small)
                )
                container.add_item(discord.ui.TextDisplay("-# SentriX Groupe Bot's --- SentriX"))

                # Même disposition que la capture : 2 boutons, 2 boutons, puis 1 bouton.
                row1 = discord.ui.ActionRow()
                configure_btn = discord.ui.Button(
                    label="Configurer SentriX",
                    emoji="⚙️",
                    style=discord.ButtonStyle.secondary,
                )
                summary_btn = discord.ui.Button(
                    label="Résumé",
                    emoji="📋",
                    style=discord.ButtonStyle.secondary,
                )
                configure_btn.callback = self._configure_clicked
                summary_btn.callback = self._summary_clicked
                row1.add_item(configure_btn)
                row1.add_item(summary_btn)
                container.add_item(row1)

                row2 = discord.ui.ActionRow()
                history_btn = discord.ui.Button(
                    label="Historique",
                    emoji="📜",
                    style=discord.ButtonStyle.secondary,
                )
                history_btn.callback = self._history_clicked
                row2.add_item(history_btn)

                dashboard_url = os.getenv("DASHBOARD_PUBLIC_URL") or DASHBOARD_FALLBACK
                dashboard_btn = discord.ui.Button(
                    label="Dashboard",
                    emoji="🏠",
                    style=discord.ButtonStyle.link,
                    url=dashboard_url,
                )
                row2.add_item(dashboard_btn)
                container.add_item(row2)

                row3 = discord.ui.ActionRow()
                close_btn = discord.ui.Button(
                    label="Fermer",
                    emoji="✖️",
                    style=discord.ButtonStyle.secondary,
                )
                close_btn.callback = self._close_clicked
                row3.add_item(close_btn)
                container.add_item(row3)

                self.add_item(container)

            async def _allowed(self, interaction: discord.Interaction) -> bool:
                return await self.cog._can_use_setup(interaction, self.author_id, self.guild_id)

            async def _configure_clicked(self, interaction: discord.Interaction):
                if not await self._allowed(interaction):
                    return

                existing = self.cog.active_by_guild.get(self.guild_id)
                if existing and existing[1] != interaction.user.id:
                    return await interaction.response.send_message(
                        f"Une configuration est déjà ouverte par **{existing[2]}**.",
                        ephemeral=True,
                    )

                await interaction.response.defer(ephemeral=True)
                try:
                    # Appel DIRECT de l'ancien moteur : il crée la vraie session persistante
                    # et toutes les pages de réglage sans repasser par le devant Components V2.
                    await original_open_setup_panel(
                        self.cog,
                        interaction.channel,
                        author=interaction.user,
                    )
                except Exception:
                    logger.exception("Impossible d'ouvrir les pages internes de +setup.")
                    return await interaction.followup.send(
                        "Impossible d'ouvrir la configuration. Réessaie `+setup`.",
                        ephemeral=True,
                    )

                try:
                    if interaction.message:
                        await interaction.message.delete()
                except discord.HTTPException:
                    pass
                await interaction.followup.send("Configuration SentriX ouverte.", ephemeral=True)
                self.stop()

            async def _summary_clicked(self, interaction: discord.Interaction):
                if not await self._allowed(interaction):
                    return
                conf = await self.cog.bot.db.get_guild_config(self.guild_id)
                if conf is None:
                    return await interaction.response.send_message(
                        "Aucune configuration enregistrée sur ce serveur.",
                        ephemeral=True,
                    )

                def configured(value) -> str:
                    return "✅" if value else "—"

                text = (
                    f"**Préfixe :** `{conf['prefix'] or '+'}`\n"
                    f"**Rôle staff :** {configured(conf['mod_role'])}\n"
                    f"**Logs :** {configured(conf['log_channel'])}\n"
                    f"**Bienvenue :** {configured(conf['welcome_channel'])}\n"
                    f"**Rôle automatique :** {configured(conf['autorole'])}"
                )
                await interaction.response.send_message(
                    embed=embeds.neutral("📋 Résumé SentriX", text, color=PURPLE_MAIN),
                    ephemeral=True,
                )

            async def _history_clicked(self, interaction: discord.Interaction):
                if not await self._allowed(interaction):
                    return
                rows = await self.cog.bot.db.list_setup_history(self.guild_id, limit=10)
                if not rows:
                    return await interaction.response.send_message(
                        "Aucune modification enregistrée pour l'instant.",
                        ephemeral=True,
                    )
                lines = [
                    f"<t:{row['created_at']}:R> • **{row['module']}** — {row['action']}"
                    for row in rows
                ]
                await interaction.response.send_message(
                    embed=embeds.neutral("📜 Historique", "\n".join(lines)[:3900], color=PURPLE_MAIN),
                    ephemeral=True,
                )

            async def _close_clicked(self, interaction: discord.Interaction):
                if not await self._allowed(interaction):
                    return
                await interaction.response.defer()
                try:
                    if interaction.message:
                        await interaction.message.delete()
                except discord.HTTPException:
                    pass
                self.stop()

        async def open_setup_landing(self, ctx_or_channel, *, author: discord.Member = None):
            # La prise de contrôle d'une session déjà ouverte doit continuer directement
            # vers le vrai panneau, sans afficher une seconde page d'accueil.
            if author is not None and not isinstance(ctx_or_channel, commands.Context):
                return await original_open_setup_panel(self, ctx_or_channel, author=author)

            guild = ctx_or_channel.guild if hasattr(ctx_or_channel, "guild") else None
            if guild is None:
                return await original_open_setup_panel(self, ctx_or_channel, author=author)

            current_author = author or getattr(ctx_or_channel, "author", None)
            if current_author is None:
                return await original_open_setup_panel(self, ctx_or_channel, author=author)

            conf = await self.bot.db.get_guild_config(guild.id)
            prefix = conf["prefix"] if conf and conf["prefix"] else "+"
            header_file = await _build_header_file(self.bot)
            landing = SetupLandingView(
                self,
                guild=guild,
                author=current_author,
                prefix=prefix,
                header_file=header_file,
            )
            return await ctx_or_channel.send(view=landing)

        configuration.Configuration._open_setup_panel = open_setup_landing
        logger.info("Devant Components V2 exact de +setup chargé.")
    else:
        logger.warning(
            "Components V2 indisponibles (discord.py < 2.6) : +setup garde le fallback embed."
        )

    _INSTALLED = True
