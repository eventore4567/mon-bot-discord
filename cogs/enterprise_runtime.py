"""Installation idempotente de la suite Enterprise depuis le chargeur historique des cogs."""
from __future__ import annotations

from discord.ext import commands


async def install(bot: commands.Bot):
    service = bot.get_cog("EnterpriseSuite")
    if service is not None:
        return service
    from .enterprise_suite import setup

    await setup(bot)
    return bot.get_cog("EnterpriseSuite")
