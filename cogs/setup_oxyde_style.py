"""Refonte visuelle de +setup inspirée des panneaux premium Discord.

Le module ne change aucune donnée ni logique de configuration : il remplace uniquement
la présentation (accueil, palette, titres, footer et navigation d'accueil). Cela permet
de conserver toute la fiabilité du SetupView existant et ses boutons persistants.
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger("bot.setup-premium-style")
_INSTALLED = False

# Violet profond proche du rendu premium de la référence fournie, tout en restant dans
# l'identité SentriX.
PURPLE_MAIN = 0x8B5CF6
PURPLE_SECONDARY = 0xA855F7


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


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import configuration

    # Toute l'interface /setup (modals compris) reprend la nouvelle palette.
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

        if missing:
            global_state = f"⚪ {missing} module(s) à terminer"
        elif partial:
            global_state = f"🟡 {partial} module(s) partiellement configuré(s)"
        else:
            global_state = "🟢 Configuration complète"

        e = discord.Embed(color=PURPLE_MAIN)
        avatar = _avatar_url(self.bot)
        _set_author(e, self.bot)
        e.title = "👋・Salut, je suis SentriX"
        e.description = (
            f"Mon préfixe sur ce serveur est **`{prefix}`**\n"
            f"Pour obtenir la liste des commandes, tape **`{prefix}help`**.\n"
            "Je suis aussi disponible en commandes slash `/`.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "**Configure ton serveur depuis ce panneau.** Choisis simplement un module dans "
            "le menu en dessous : tu n'as pas besoin de retenir toutes les commandes de réglage."
        )

        server_name = guild.name if guild else "Serveur inconnu"
        e.add_field(
            name="⚙️・État de la configuration",
            value=(
                f"**Serveur :** {server_name}\n"
                f"**Modules prêts :** {configured}/{len(categories)}\n"
                f"**État :** {global_state}"
            ),
            inline=False,
        )

        category_lines = [
            f"{_status_icon(status)} **{name}** — {status.lower()}"
            for name, status in categories
        ]
        e.add_field(
            name="📂・Modules",
            value="\n".join(category_lines),
            inline=False,
        )
        e.add_field(
            name="💡・Utilisation",
            value=(
                "**1.** Choisis un module dans le menu.\n"
                "**2.** Modifie les rôles, salons ou protections.\n"
                "**3.** Clique sur **Enregistrer**.\n"
                "**4.** Utilise **Résumé** pour vérifier que tout est prêt."
            ),
            inline=False,
        )

        if avatar:
            e.set_thumbnail(url=avatar)
        e.set_footer(text=f"SentriX • {server_name} • Centre de configuration")
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
        e.set_footer(
            text=(
                f"SentriX • {guild.name if guild else 'Serveur'} • "
                "Les changements indiqués comme immédiats sont déjà enregistrés"
            )
        )
        return e

    def render_home(self) -> None:
        """Accueil compact : un menu principal + quatre boutons, comme les bots premium."""
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

        self.add_item(configuration.SetupNavButton(
            "save", self.message_id,
            label="💾 Enregistrer",
            style=discord.ButtonStyle.success,
            row=1,
        ))
        self.add_item(configuration.SetupNavButton(
            "summary", self.message_id,
            label="📋 Résumé",
            style=discord.ButtonStyle.primary,
            row=1,
        ))
        self.add_item(configuration.SetupNavButton(
            "history", self.message_id,
            label="📜 Historique",
            style=discord.ButtonStyle.secondary,
            row=1,
        ))
        self.add_item(configuration.SetupNavButton(
            "cancel", self.message_id,
            label="✖ Fermer",
            style=discord.ButtonStyle.danger,
            row=1,
        ))

    configuration.SetupView._build_home_embed = build_home_embed
    configuration.SetupView.build_embed = build_embed
    configuration.SetupView._render_home = render_home

    _INSTALLED = True
    logger.info("Nouveau style premium violet de +setup chargé.")
