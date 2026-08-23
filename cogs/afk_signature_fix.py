"""Corrige la signature publique de +afk et active les runtimes bot-only garantis."""

from __future__ import annotations

import logging

from discord.ext import commands

logger = logging.getLogger("bot.afk-signature")


def _install_v14(bot: commands.Bot) -> None:
    """Charge la couche bot-only V14 depuis un installateur déjà garanti au démarrage."""
    try:
        from .bot_v14_core import install as install_v14
        install_v14(bot)
    except Exception:
        # Une optimisation ne doit jamais empêcher +afk ni le reste des cogs de démarrer.
        logger.exception("Impossible d'activer SentriX V14 Core ; le bot continue en mode normal.")


def _install_ai_guard(bot: commands.Bot) -> None:
    """Active le verrou global du bouton IA, même si le Cog Ai est chargé un peu plus tard."""
    try:
        from .ai_disable_guard import install as install_ai_disable_guard
        install_ai_disable_guard(bot)
    except Exception:
        logger.exception("Impossible d'activer le verrou global IA ; le bot continue.")


def install(bot: commands.Bot) -> None:
    """Garde uniquement la raison facultative dans les paramètres visibles de +afk."""
    # Ces deux runtimes ne dépendent pas de la présence de +afk : ils restent activés même
    # si cette commande venait à être renommée ou momentanément indisponible.
    _install_v14(bot)
    _install_ai_guard(bot)

    command = bot.get_command("afk")
    if command is None:
        logger.warning("Signature AFK non corrigée : commande introuvable.")
        return

    # Le callback amélioré est une fonction externe au Cog. discord.py ne sait donc pas
    # automatiquement que son premier paramètre est l'instance Utility et expose `ctx`
    # comme argument utilisateur. Le retirer de `params` conserve l'appel interne normal :
    # callback(utility, ctx, raison=...).
    command.params.pop("ctx", None)

    reason = command.params.get("raison")
    if reason is not None:
        reason._description = "Raison facultative de votre absence"

    logger.info("Signature +afk corrigée : raison facultative, aucun argument obligatoire.")
