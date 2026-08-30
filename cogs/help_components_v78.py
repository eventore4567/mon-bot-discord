"""SentriX V78 — corrige le Help Components V2 qui dépassait la limite Discord.

Discord limite un message Components V2 à 40 composants au total. La page d'accueil V77
pouvait dépasser cette limite lorsqu'elle affichait toutes les catégories avec chacune un
bouton. V78 conserve exactement le même style, mais pagine l'accueil par 6 catégories.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from . import help_components_v77 as v77
from . import setup_components_v73 as setup_v73

logger = logging.getLogger("bot.help-components-v78")
RUNTIME_MARKER = "Help Components V2 V78"
HOME_PAGE_SIZE = 6


def _show_home_v78(self: v77.SentriXHelpV77) -> None:
    self.mode = "home"
    self.category_key = None
    self.rows = []
    self.query = None
    self.command = None
    self.home_index = 0


def _build_home_v78(self: v77.SentriXHelpV77) -> None:
    grouped = v77._grouped(self.bot, self.member)
    total = sum(len(rows) for rows in grouped.values())
    slash_count = len(v77.legacy._slash_map(self.bot))
    visible_keys = list(grouped.keys())
    page_count = max(1, (len(visible_keys) + HOME_PAGE_SIZE - 1) // HOME_PAGE_SIZE)
    page_index = min(max(int(getattr(self, "home_index", 0)), 0), page_count - 1)
    self.home_index = page_index
    start = page_index * HOME_PAGE_SIZE
    page_keys = visible_keys[start:start + HOME_PAGE_SIZE]

    container = discord.ui.Container(accent_colour=setup_v73.ACCENT)
    container.add_item(
        discord.ui.Section(
            discord.ui.TextDisplay(
                "# Centre d'aide SentriX\n"
                "**Bienvenue dans l'aide de SentriX.** Choisissez une catégorie pour voir "
                "les commandes, ou utilisez la recherche pour trouver directement ce qu'il vous faut.\n\n"
                f"**{total} commandes disponibles** · **{slash_count} commandes slash détectées**\n"
                f"Catégories : page **{page_index + 1}/{page_count}**\n"
                "Toutes les commandes restent visibles, y compris les commandes administratives."
            ),
            accessory=setup_v73._thumbnail(self.bot),
        )
    )
    container.add_item(discord.ui.Separator())

    for index, key in enumerate(page_keys):
        emoji, label, description = v77._meta(key)
        rows = grouped[key]
        button = discord.ui.Button(label="Voir les commandes", style=discord.ButtonStyle.secondary)

        async def open_category(interaction: discord.Interaction, category_key=key):
            self.show_category(category_key)
            await self.refresh(interaction)

        button.callback = open_category
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    f"## {emoji} {label}\n{description}\n**{len(rows)} commande(s)**"
                ),
                accessory=button,
            )
        )
        if index == 2 and len(page_keys) > 3:
            container.add_item(discord.ui.Separator())

    previous = discord.ui.Button(
        label="Précédent",
        style=discord.ButtonStyle.secondary,
        disabled=page_index <= 0,
    )
    search = discord.ui.Button(
        label="Rechercher",
        style=discord.ButtonStyle.primary,
        emoji="🔎",
    )
    next_button = discord.ui.Button(
        label="Suivant",
        style=discord.ButtonStyle.secondary,
        disabled=page_index >= page_count - 1,
    )
    close = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.danger)

    async def go_previous(interaction: discord.Interaction):
        self.home_index = max(0, int(getattr(self, "home_index", 0)) - 1)
        await self.refresh(interaction)

    async def open_search(interaction: discord.Interaction):
        await interaction.response.send_modal(v77.HelpSearchModalV77(self))

    async def go_next(interaction: discord.Interaction):
        self.home_index = min(page_count - 1, int(getattr(self, "home_index", 0)) + 1)
        await self.refresh(interaction)

    async def close_help(interaction: discord.Interaction):
        self.mode = "closed"
        await self.refresh(interaction)
        self.stop()

    previous.callback = go_previous
    search.callback = open_search
    next_button.callback = go_next
    close.callback = close_help

    container.add_item(discord.ui.Separator())
    container.add_item(discord.ui.ActionRow(previous, search, next_button, close))

    links = v77._link_buttons(self.bot)
    if links:
        container.add_item(discord.ui.ActionRow(*links))
    self.add_item(container)


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_help_components_v78", False):
        return
    cls = v77.SentriXHelpV77

    current_home = cls._build_home
    if not getattr(current_home, "_sentrix_help_v78", False):
        _build_home_v78._sentrix_help_v78 = True
        _build_home_v78._sentrix_previous = current_home
        cls._build_home = _build_home_v78

    current_show_home = cls.show_home
    if not getattr(current_show_home, "_sentrix_help_v78", False):
        _show_home_v78._sentrix_help_v78 = True
        _show_home_v78._sentrix_previous = current_show_home
        cls.show_home = _show_home_v78

    bot._sentrix_help_components_v78 = True
    logger.info(
        "%s installé : accueil du Help paginé à %s catégories pour respecter la limite Components V2.",
        RUNTIME_MARKER,
        HOME_PAGE_SIZE,
    )


__all__ = ["install", "HOME_PAGE_SIZE"]
