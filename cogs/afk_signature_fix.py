"""Corrige la signature publique de +afk après l'installation du renommage AFK."""

from __future__ import annotations

import logging

from discord.ext import commands

logger = logging.getLogger("bot.afk-signature")


def install(bot: commands.Bot) -> None:
    """Garde uniquement la raison facultative dans les paramètres visibles de +afk."""
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
