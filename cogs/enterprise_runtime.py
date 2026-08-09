"""Installation idempotente de la suite Enterprise depuis le chargeur historique des cogs."""
from __future__ import annotations

import asyncio

from discord.ext import commands


async def install(bot: commands.Bot):
    service = bot.get_cog("EnterpriseSuite")
    if service is not None:
        return service

    from . import enterprise_suite as module

    async def ready(self):
        try:
            await self.bot.wait_until_ready()
        except RuntimeError:
            # Bot construit hors connexion (audits CI) : aucune boucle de fond ne doit
            # exécuter son premier tick contre un client Discord jamais démarré.
            raise asyncio.CancelledError

    async def ready_backup(self):
        try:
            await self.bot.wait_until_ready()
        except RuntimeError:
            raise asyncio.CancelledError
        await asyncio.sleep(90)

    if not getattr(module.EnterpriseSuite, "_sentrix_safe_before_loops", False):
        module.EnterpriseSuite.metrics_loop.before_loop(ready)
        module.EnterpriseSuite.automation_loop.before_loop(ready)
        module.EnterpriseSuite.analytics_loop.before_loop(ready)
        module.EnterpriseSuite.backup_loop.before_loop(ready_backup)
        module.EnterpriseSuite._sentrix_safe_before_loops = True

    await module.setup(bot)
    return bot.get_cog("EnterpriseSuite")
