"""Finalisation produit légère du runtime SentriX.

Les anciens restaurateurs V2/V3 ne sont plus utilisés. Une seule surface utilisateur est
finalisée ici : registre slash utile + aide simple. Les fonctionnalités métier restent dans
leurs Cogs historiques pour préserver la compatibilité des commandes +.
"""
from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord.ext import commands

from . import slash_command_budget

# Le garde slash doit être actif avant le premier Cog.
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


async def install(bot: commands.Bot) -> None:
    """Finalise une seule fois la surface produit visible par les utilisateurs."""
    _install_odboug_account_username(bot)

    # Propriétaire unique du registre `/` : restaure les anciennes commandes utiles,
    # garde les centres regroupés et respecte strictement le plafond Discord.
    try:
        from . import easy_command_surface
        await easy_command_surface.install(bot)
    except Exception:
        logger.exception("Surface slash canonique impossible à finaliser.")

    # Propriétaire unique de +help / /help. Cette installation arrive après les anciennes
    # couches d'aide : elles ne peuvent donc plus réécrire l'accueil final.
    try:
        from . import help_simple
        help_simple.install(bot)
    except Exception:
        logger.exception("Aide simple canonique impossible à installer.")

    _schedule_safe(
        bot,
        marker="_sentrix_community_growth_scheduled_clean",
        name="sentrix-community-growth",
        coroutine=_bootstrap_community_growth(bot),
    )

    bot._sentrix_legacy_v2_runtime_disabled = True
    bot._sentrix_command_surface_owner = "cogs.easy_command_surface"
    bot._sentrix_help_owner = "cogs.help_simple"
    logger.info(
        "Finalisation produit : registre slash=%s, aide simple active, anciens restaurateurs V2/V3 inactifs.",
        getattr(bot, "_sentrix_slash_registry_count", "?"),
    )


__all__ = ["install"]
