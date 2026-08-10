"""Compatibilité : installe les centres de commandes V3."""
from __future__ import annotations

from discord.ext import commands

from . import command_giveaway_center_v3, command_ticket_center_v3


def install(bot: commands.Bot) -> None:
    command_ticket_center_v3.install(bot)
    command_giveaway_center_v3.install(bot)
