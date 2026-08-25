"""Compatibilité de bootstrap historique et dernier verrou runtime SentriX.

Railway charge ce module en dernier. Il réenregistre donc le propriétaire officiel de
+help puis installe RuntimeFixV1, qui devient la dernière couche de transport Discord :
les réponses de commandes restent de vrais embeds et les anciens salons de logs sont
resynchronisés avec le transport actuel.
"""
from __future__ import annotations

from discord.ext import commands

from .help import OfficialHelp
from . import runtime_fix_v1


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

    # IMPORTANT : ce module étant chargé en dernier par railway_boot.py, le correctif
    # runtime doit lui aussi être installé ici, après tous les anciens renderers/cogs.
    await runtime_fix_v1.setup(bot)
