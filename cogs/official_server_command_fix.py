"""Correctifs runtime du serveur officiel SentriX.

Historiquement cette couche posait l'alias texte ``+sentrix-server`` sur la commande
``create-server``. Toutes les commandes de création de serveur ont été retirées ; il
reste ici l'installation des deux correctifs qui n'ont jamais dépendu de la commande :
l'identification du serveur officiel et le journal d'ajouts ``#serveurs-sentrix`` (V62).
"""
from __future__ import annotations

import logging

from discord.ext import commands


logger = logging.getLogger("bot.official-server-command-fix")


def install(bot: commands.Bot) -> None:
    runtime = getattr(bot, "_sentrix_official_server_runtime", None)
    if runtime is None:
        return

    # L'invitation officielle devient prioritaire sur les anciens IDs persistants
    # éventuellement obsolètes.
    try:
        from .official_server_binding_fix import install as install_binding_fix
        install_binding_fix(bot)
    except Exception:
        logger.exception("Impossible d'installer le correctif d'identification du serveur officiel.")

    # V62 transforme #serveurs-sentrix en journal d'ajouts uniquement.
    try:
        from .official_server_join_feed_v62 import install as install_join_feed_v62
        install_join_feed_v62(bot)
    except Exception:
        logger.exception("Impossible d'installer le journal d'ajouts serveurs V62.")


__all__ = ["install"]
