"""Finalisation légère du runtime SentriX.

Les anciennes piles V2/V2.1/V2.2/V2.3/V2.4 et les restaurateurs V3 de commandes ne sont
plus chargés ici. Les fonctionnalités métier restent dans leurs vrais Cogs ; cette couche
ne fait que préparer très tôt le registre slash, nettoyer la surface visible et conserver
les opérations d'instance non conflictuelles.
"""
from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord.ext import commands

from . import slash_command_budget

# Important : final_runtime_polish est importé par cogs.__init__ pendant l'import du
# package, donc avant le setup du premier Cog. Le plafond slash est ainsi actif à temps.
slash_command_budget.install_class_guard()

logger = logging.getLogger("bot.final-runtime")


def _install_odboug_account_username(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_odboug_account_username_installed", False):
        return
    from utils.instance_identity import is_odboug_instance
    if not is_odboug_instance():
        return
    desired = (os.getenv("BOT_ACCOUNT_USERNAME") or "Odboug bot").strip()[:32]
    if not desired:
        return

    async def apply_username():
        user = bot.user
        if user is None or user.name == desired:
            return
        try:
            await user.edit(username=desired)
        except discord.HTTPException:
            logger.exception("Discord a refusé le username d'instance %r.", desired)

    bot.add_listener(apply_username, "on_ready")
    bot._sentrix_odboug_account_username_installed = True


def _schedule_safe(bot: commands.Bot, *, marker: str, name: str, coroutine) -> None:
    """Crée une tâche optionnelle avec récupération explicite de son exception."""
    if getattr(bot, marker, False):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    setattr(bot, marker, True)
    task = loop.create_task(coroutine, name=name)

    def finished(done: asyncio.Task):
        try:
            done.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Tâche runtime %s terminée en erreur.", name)

    task.add_done_callback(finished)


async def _bootstrap_community_growth(bot: commands.Bot) -> None:
    """Fonction métier conservée, sans installer de renderer ou de politique de commandes."""
    if getattr(bot, "_sentrix_community_growth_ready", False):
        return
    try:
        from . import community_growth
        await community_growth.setup(bot)
        from web import dashboard
        from web import community_card_polish
        from web import community_growth as community_dashboard
        community_dashboard.install(dashboard)
        community_card_polish.install(dashboard)
        bot._sentrix_community_growth_ready = True
    except Exception:
        logger.exception("Community Growth impossible à initialiser.")


def _clean_command_surface(bot: commands.Bot) -> None:
    """Un seul nettoyeur de catalogue ; aucun restaurateur/alias V2/V3 n'est réappliqué."""
    try:
        from . import command_catalog_cleanup
        command_catalog_cleanup.install(bot)
    except Exception:
        logger.exception("Nettoyage du catalogue de commandes impossible.")
    slash_command_budget.finalize(bot)


def install(bot: commands.Bot) -> None:
    _install_odboug_account_username(bot)
    _clean_command_surface(bot)
    _schedule_safe(
        bot,
        marker="_sentrix_community_growth_scheduled_clean",
        name="sentrix-community-growth",
        coroutine=_bootstrap_community_growth(bot),
    )
    bot._sentrix_legacy_v2_runtime_disabled = True
    bot._sentrix_command_surface_owner = "command_catalog_cleanup + slash_command_budget"
    logger.info(
        "Finalisation propre : runtimes V2/V3 retirés, catalogue unique, registre slash=%s.",
        getattr(bot, "_sentrix_slash_registry_count", "?"),
    )


__all__ = ["install"]
