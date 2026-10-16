"""Écrit dans le journal, une fois par démarrage du leader, l'usage réel des commandes.

Le résumé (utils/command_usage.py) ne contient que des comptes par commande : il
peut être lu dans les journaux Railway sans ouvrir la base de production.
"""
from __future__ import annotations

import asyncio
import logging

from discord.ext import commands

from utils import cluster, command_usage

logger = logging.getLogger("bot.command-usage")

DELAI_SECONDES = 90  # après le démarrage : ne pas concurrencer la synchro et les caches


def catalogue(bot: commands.Bot) -> list[str]:
    return sorted({c.qualified_name for c in bot.walk_commands() if not getattr(c, "hidden", False)})


class CommandUsageReport(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._tache: asyncio.Task | None = None

    @commands.Cog.listener()
    async def on_ready(self):
        if self._tache is None and cluster.is_primary_cluster():
            self._tache = asyncio.create_task(self._ecrire(), name="sentrix:command-usage")

    async def _ecrire(self) -> None:
        await asyncio.sleep(DELAI_SECONDES)
        try:
            r = await command_usage.resume(self.bot.db, catalogue(self.bot))
        except Exception:
            logger.warning("Résumé d'usage des commandes indisponible.", exc_info=True)
            return
        for ligne in command_usage.lignes_de_journal(r):
            logger.info(ligne)

    def cog_unload(self):
        if self._tache is not None:
            self._tache.cancel()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CommandUsageReport(bot))
