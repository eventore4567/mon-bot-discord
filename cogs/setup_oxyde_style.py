"""Style premium stable de +setup, inspiré du mockup SentriX/OXYDE.

IMPORTANT : ce module ne touche qu'à la présentation de +setup.
Il utilise uniquement les composants Discord standards disponibles en discord.py 2.4+
(Embed, Select, Button). Aucun Components V2, aucune image générée à la volée.
"""

from __future__ import annotations

import logging
import os

import discord
from discord.ext import commands

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


def _invite_url(bot: commands.Bot) -> str | None:
    user = getattr(bot, "user", None)
    if user is None:
        return None
    try:
        return discord.utils.oauth_url(
            user.id,
            permissions=discord.Permissions(administrator=True),
            scopes=("bot", "applications.commands"),
        )
    except Exception:
        logger.exception("Impossible de générer le lien d'invitation SentriX.")
        return None


def _safe_http_url(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if value.startswith("https://") or value.startswith("http://"):
        return value
    return None


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import configuration

    configuration.SETUP_COLOR_MAIN = PURPLE_MAIN
    configuration.SETUP_COLOR_SECONDARY = PURPLE_SECONDARY

    original_build_embed = configuration.SetupView.build_embed

    async def build_home_embed(self) -> discord.Embed:
        conf = await self.bot.db.get_guild_config(self.guild_id)
        guild = self._guild()
        categories = await self._compute_categories(conf)
        prefix = conf["prefix"] if conf and conf["prefix"] else "+"

        configured = sum(1 for _, status in categories if status == "Configuré")
        partial = sum(1 for _, status in categories if status == "Partiel")
        missing = sum(1 for _, status in categories if status == "Non configuré")

        if missing == 0 and partial == 0:
            server_state = "🟢 Configuré"
        elif missing <= 1:
            server_state = "🟡 Presque prêt"
        else:
            server_state = "🟣 À configurer"

        e = discord.Embed(color=PURPLE_MAIN)
        _set_author(e, self.bot)
        e.title = "👋 • Salut, je suis SentriX"
        e.description = (
            "Je suis là pour **protéger, gérer et améliorer ton serveur**.\n"
            "Configure-moi facilement depuis ce panneau ou avec mes commandes.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⌨️  Mon préfixe sur ce serveur est **`{prefix}`**\n\n"
            f"📖  Pour obtenir la liste des commandes, tape **`{prefix}help`**\n\n"
            "◉  Je suis aussi disponible en **slash commande `/`**."
        )

        e.add_field(name="＃ PRÉFIXE", value=f"**`{prefix}`**", inline=True)
        e.add_field(name="◈ MODULES", value=f"**{configured}/{len(categories)}** prêts", inline=True)
        e.add_field(name="◉ SERVEUR", value=server_state, inline=True)

        if partial or missing:
            todo = []
            for name, status in categories:
                if status != "Configuré":
                    todo.append(f"• **{name}** — {status.lower()}")
            e.add_field(
                name="⚙️ • Configuration restante",
                value="\n".join(todo)[:1024],
                inline=False,
            )
        else:
            e.add_field(
                name="✅ • Configuration",
                value="Tous les modules principaux de ce panneau sont configurés.",
                inline=False,
            )

        avatar = _avatar_url(self.bot)
        if avatar:
            e.set_thumbnail(url=avatar)

        server_name = guild.name if guild else "Serveur"
        e.set_footer(text=f"SentriX • {server_name} • Sécurise, automatise, simplifie.")
        return e

    async def build_embed(self) -> discord.Embed:
        if self.page == -1:
            return await build_home_embed(self)

        e = await original_build_embed(self)
        step = configuration.SETUP_STEPS[self.page]
        guild = self._guild()
        avatar = _avatar_url(self.bot)

        e.colour = discord.Colour(PURPLE_MAIN)
        e.title = f"{step['icon']} • {step['title']}"
        _set_author(e, self.bot)
        if avatar:
            e.set_thumbnail(url=avatar)
        e.set_footer(
            text=(
                f"SentriX • {guild.name if guild else 'Serveur'} • "
                "Centre de configuration"
            )
        )
        return e

    def render_home(self) -> None:
        """Accueil proche du mockup, mais composé uniquement d'éléments Discord standards."""
        self.clear_items()

        category_select = discord.ui.Select(
            placeholder="⚙️ Choisir un module à configurer",
            options=[
                discord.SelectOption(
                    label=f"{step['icon']} {step['title']}"[:100],
                    value=str(index),
                    description=(step.get("description") or f"Configurer {step['title'].lower()}")[:100],
                )
                for index, step in enumerate(configuration.SETUP_STEPS)
                if step["key"] != "summary"
            ],
            row=0,
        )
        category_select.callback = self._make_home_category_callback(category_select)
        self.add_item(category_select)

        # Liens : aucun callback -> ils restent fiables même après un redémarrage du bot.
        invite_url = _invite_url(self.bot)
        dashboard_url = _safe_http_url(os.getenv("DASHBOARD_PUBLIC_URL")) or DASHBOARD_FALLBACK
        support_url = _safe_http_url(os.getenv("SUPPORT_SERVER_URL"))
        status_url = _safe_http_url(os.getenv("STATUS_PUBLIC_URL"))

        if invite_url:
            self.add_item(discord.ui.Button(
                label="Inviter SentriX",
                emoji="👥",
                style=discord.ButtonStyle.link,
                url=invite_url,
                row=1,
            ))
        self.add_item(discord.ui.Button(
            label="Dashboard",
            emoji="📈",
            style=discord.ButtonStyle.link,
            url=dashboard_url,
            row=1,
        ))
        if support_url:
            self.add_item(discord.ui.Button(
                label="Serveur support",
                emoji="🎧",
                style=discord.ButtonStyle.link,
                url=support_url,
                row=1,
            ))
        if status_url:
            self.add_item(discord.ui.Button(
                label="Statut",
                emoji="📡",
                style=discord.ButtonStyle.link,
                url=status_url,
                row=1,
            ))

        # Navigation existante : on réutilise les DynamicItem du vrai setup pour garder
        # la persistance après redémarrage et ne rien casser dans la logique actuelle.
        self.add_item(configuration.SetupNavButton(
            "save", self.message_id,
            label="💾 Enregistrer",
            style=discord.ButtonStyle.success,
            row=2,
        ))
        self.add_item(configuration.SetupNavButton(
            "summary", self.message_id,
            label="📋 Résumé",
            style=discord.ButtonStyle.primary,
            row=2,
        ))
        self.add_item(configuration.SetupNavButton(
            "history", self.message_id,
            label="🕘 Historique",
            style=discord.ButtonStyle.secondary,
            row=2,
        ))
        self.add_item(configuration.SetupNavButton(
            "cancel", self.message_id,
            label="✖ Fermer",
            style=discord.ButtonStyle.danger,
            row=2,
        ))

    configuration.SetupView._build_home_embed = build_home_embed
    configuration.SetupView.build_embed = build_embed
    configuration.SetupView._render_home = render_home

    _INSTALLED = True
    logger.info("Style premium stable de +setup chargé (Embed + composants standards).")
