"""V100 — rend ``InteractionResponse.defer`` idempotent pour la passerelle slash.

La passerelle V99 defer l'interaction avant d'invoquer la commande historique. Plusieurs
commandes (notamment IA) defer aussi elles-mêmes via ``ctx.defer()``. Discord.py levait
alors ``InteractionResponded`` avant même que la logique métier ne s'exécute.
"""
from __future__ import annotations

import logging
from typing import Any

import discord

logger = logging.getLogger("bot.v100-defer")
_INSTALLED = False


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    current = discord.InteractionResponse.defer
    if getattr(current, "_sentrix_v100_idempotent_defer", False):
        _INSTALLED = True
        return

    async def guarded_defer(self: discord.InteractionResponse, *args: Any, **kwargs: Any):
        if self.is_done():
            logger.debug("V100: defer déjà effectué, second defer ignoré.")
            return None
        try:
            return await current(self, *args, **kwargs)
        except discord.InteractionResponded:
            logger.debug("V100: course de defer déjà acquittée, exception neutralisée.")
            return None
        except discord.HTTPException as exc:
            if getattr(exc, "code", None) == 40060:
                logger.debug("V100: Discord 40060 sur defer déjà acquitté, neutralisé.")
                return None
            raise

    guarded_defer._sentrix_v100_idempotent_defer = True
    guarded_defer._sentrix_v100_original = current
    discord.InteractionResponse.defer = guarded_defer
    _INSTALLED = True
    logger.info("V100: defer d'interaction idempotent installé.")


__all__ = ["install"]
