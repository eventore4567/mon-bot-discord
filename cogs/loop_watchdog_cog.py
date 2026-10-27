"""Branche utils/loop_watchdog : un module install()-seul ne tourne pas en
production, d'où un vrai setup() listé dans main.EXTENSIONS.

Lancé APRÈS on_ready (et 30 s de marge) : le chargement des modules bloque la
boucle plusieurs secondes à chaque démarrage, ce qui n'est pas la lenteur cherchée."""
from __future__ import annotations

import asyncio
import logging

from discord.ext import commands

from utils import loop_watchdog

logger = logging.getLogger("bot.loop-watchdog")

MARGE_APRES_DEMARRAGE_S = 30


class LoopWatchdog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._tache: asyncio.Task | None = None

    async def cog_load(self) -> None:
        # Pas d'écouteur on_ready de plus (budget d'écouteurs, tests/test_runtime_hygiene_gates) :
        # une tâche attend que le bot soit prêt.
        self._tache = asyncio.create_task(self._lancer(), name="sentrix:loop-watchdog-start")

    async def _lancer(self) -> None:
        # is_ready() et non wait_until_ready() : ce dernier lève si le cog est
        # chargé avant la connexion du client.
        while not self.bot.is_ready():
            await asyncio.sleep(1)
        await asyncio.sleep(MARGE_APRES_DEMARRAGE_S)
        if loop_watchdog.demarrer(asyncio.get_running_loop()):
            logger.info("Détecteur de blocage de boucle actif (seuil %.1f s).", loop_watchdog.SEUIL_S)

    def cog_unload(self):
        if self._tache is not None:
            self._tache.cancel()
        loop_watchdog.arreter()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LoopWatchdog(bot))
