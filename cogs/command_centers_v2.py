"""Compatibilité : installe les centres de commandes V3."""
from __future__ import annotations

from dataclasses import replace

from discord.ext import commands

from . import command_giveaway_center_v3, command_ticket_center_v3


def _categorize_giveaway() -> None:
    from . import help_complete

    updated = []
    changed = False
    for category in help_complete.CATEGORIES:
        if category.key == "events" and "giveaway" not in category.roots:
            category = replace(category, roots=category.roots | {"giveaway"})
            changed = True
        updated.append(category)
    if changed:
        help_complete.CATEGORIES = tuple(updated)
        help_complete.CATEGORY_BY_KEY = {
            category.key: category for category in help_complete.CATEGORIES
        }


def install(bot: commands.Bot) -> None:
    command_ticket_center_v3.install(bot)
    command_giveaway_center_v3.install(bot)
    _categorize_giveaway()
