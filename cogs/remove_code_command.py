"""Compatibilité historique du loader IA et catalogue complet des commandes."""

from __future__ import annotations

import asyncio
import logging

from discord.ext import commands

from .bot_mastery_runtime import install as install_bot_mastery
from .command_catalog_cleanup import install as install_command_catalog_cleanup
from .operations_center import install as install_operations_center

logger = logging.getLogger("bot.remove-code-command")
_INSTALLED = False
_MASTERY_READY_TASK = None


async def _finish_mastery_after_ready(bot: commands.Bot) -> None:
    """Deuxième passage après READY : Music/Events/Invites sont alors tous chargés."""
    try:
        await bot.wait_until_ready()
        await asyncio.sleep(1)
        await install_bot_mastery(bot, "ready")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Deuxième passage Bot Mastery impossible ; le bot continue.")


async def install(bot: commands.Bot) -> None:
    """Applique le catalogue canonique, Operations, Mastery et conserve +code."""
    # Cette fonction est appelée pendant le chargement du cog IA, donc avant le pruning
    # final de main.setup_hook(). À ce moment AutoMod/Tickets/Configuration sont déjà
    # chargés : Operations et Mastery peuvent brancher leurs protections sans créer de
    # nouvelle racine de commande. Un second passage READY finit les patches dépendants
    # des cogs chargés plus tard (notamment Music).
    install_command_catalog_cleanup(bot)
    await install_operations_center(bot)
    await install_bot_mastery(bot, "cogs.ai")

    global _MASTERY_READY_TASK
    session_started = bool(getattr(getattr(bot, "http", None), "token", None))
    if session_started and (_MASTERY_READY_TASK is None or _MASTERY_READY_TASK.done()):
        _MASTERY_READY_TASK = asyncio.create_task(_finish_mastery_after_ready(bot))

    global _INSTALLED
    if _INSTALLED:
        return

    command = bot.get_command("code")
    if command is not None:
        command.hidden = False
        logger.info("Commande +code conservée : raccourci IA spécialisé pour la génération de code.")
    else:
        logger.warning("Commande +code introuvable pendant le chargement du cog IA.")

    _INSTALLED = True