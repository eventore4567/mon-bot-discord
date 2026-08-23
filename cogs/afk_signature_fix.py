"""Corrige la signature publique de +afk et active le runtime V14 du bot."""

from __future__ import annotations

import logging

from discord.ext import commands

logger = logging.getLogger("bot.afk-signature")


def _install_v14(bot: commands.Bot) -> None:
    """Charge la couche bot-only V14 depuis un installateur déjà garanti au démarrage.

    Ce fichier est appelé après le chargement du cog Utility. V14 reste idempotent et
    n'ajoute aucune commande publique : il accélère uniquement les chemins runtime.
    """
    try:
        from .bot_v14_core import install as install_v14
        install_v14(bot)
    except Exception:
        # Une optimisation ne doit jamais empêcher +afk ni le reste des cogs de démarrer.
        logger.exception("Impossible d'activer SentriX V14 Core ; le bot continue en mode normal.")


def install(bot: commands.Bot) -> None:
    """Garde uniquement la raison facultative dans les paramètres visibles de +afk."""
    # V14 ne dépend pas de la présence de +afk : on l'active même si cette commande venait
    # à être renommée ou momentanément indisponible.
    _install_v14(bot)

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