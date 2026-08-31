"""V87 — garantit le routeur +create avant d'activer la finalisation V86."""
from __future__ import annotations

import logging

from discord.ext import commands

from . import runtime_finish_v86 as v86

logger = logging.getLogger("bot.runtime-finish-v87")


async def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_runtime_finish_v87", False):
        return

    # Le preset manox est un sous-groupe de la racine canonique +create. Au moment de la
    # finalisation, ServerBuilder est déjà chargé : on peut donc garantir explicitement le
    # routeur au lieu de dépendre d'un ordre d'installation implicite.
    root = bot.get_command("create")
    if not isinstance(root, commands.Group):
        from . import create_command_router

        await create_command_router.install(bot)

    v86.install(bot)

    root = bot.get_command("create")
    manox = bot.get_command("create manox")
    if not isinstance(root, commands.Group) or manox is None:
        raise RuntimeError("Routeur +create incomplet : +create manox n'a pas été installé.")

    bot._sentrix_runtime_finish_v87 = True
    logger.info("Runtime Finish V87 actif : routeur +create vérifié et preset manox présent.")


__all__ = ["install"]
