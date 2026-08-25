"""Compatibilité de bootstrap historique.

Ce nom reste temporairement référencé par railway_boot.py, mais le module ne convertit
plus aucun embed en texte et n'installe plus de renderer. Il assure seulement que le
propriétaire officiel de +help est enregistré après l'ancien Utility.
"""
from __future__ import annotations

from discord.ext import commands

from .help import OfficialHelp


async def setup(bot: commands.Bot) -> None:
    old = bot.get_command("help")
    if old is not None:
        bot.remove_command("help")
    existing = bot.get_cog("SentriXHelp")
    if existing is not None:
        await bot.remove_cog("SentriXHelp")
    # Le slash /help existant est retiré par nom avant l'enregistrement du propriétaire unique.
    try:
        import discord
        bot.tree.remove_command("help", type=discord.AppCommandType.chat_input)
    except Exception:
        pass
    await bot.add_cog(OfficialHelp(bot))
