"""Compatibilité historique des anciens guards de salons de logs.

Ce module n'installe plus aucun monkey-patch de ``discord.TextChannel.send``.
Le vieux guard pouvait convertir un échec Components V2 puis retomber sur
``channel.send(embed=..., view=...)`` : c'est exactement le rendu legacy qui pouvait
réapparaître sur les vrais événements alors que ``+logs test`` utilisait le pipeline V2.

Le transport unique est désormais : ``log_service.send_log`` -> ``send_wide_log``.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.log-guard")
_INSTALLED = False


def install() -> None:
    """No-op volontaire : l'ancien fallback global est définitivement désactivé."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    logger.info(
        "Legacy log_channel_guard désactivé : aucun fallback TextChannel.send(embed=...) n'est installé."
    )


__all__ = ["install"]
