"""SentriX V98 — cohérence des deux commandes historiques de réouverture ticket.

Le dépôt possède ``ticket-reopen`` (moteur Tickets canonique) et ``reopenticket`` (V17).
La seconde refusait toute réouverture quand ``reopen_minutes`` valait 0 alors que la première
rouvrait correctement le même ticket tant que le salon existait encore. Cela donnait deux
résultats différents pour la même action et pouvait faire croire que la réouverture était
cassée.

V98 conserve les deux noms pour compatibilité mais fait déléguer ``reopenticket`` vers le
moteur canonique ``ticket-reopen``. Les checks/permissions du Command V17 restent en place.
"""
from __future__ import annotations

import functools
import logging

from discord.ext import commands

logger = logging.getLogger("bot.v98-ticket-reopen")


def install(bot: commands.Bot) -> bool:
    legacy = bot.get_command("reopenticket")
    canonical = bot.get_command("ticket-reopen")
    if legacy is None or canonical is None:
        logger.warning(
            "V98 réouverture non installée : reopenticket=%s ticket-reopen=%s",
            bool(legacy), bool(canonical),
        )
        return False
    if getattr(legacy.callback, "_sentrix_v98_reopen_alias", False):
        return True

    original = legacy.callback

    @functools.wraps(canonical.callback)
    async def reopen_v98(self, ctx: commands.Context):
        # Appel de la logique métier canonique uniquement. Le check manage_channels du
        # Command ``reopenticket`` est toujours exécuté par discord.py avant ce callback.
        return await canonical.callback(canonical.cog, ctx)

    reopen_v98._sentrix_v98_reopen_alias = True
    reopen_v98._sentrix_original = original
    legacy.callback = reopen_v98
    logger.info("V98 : +reopenticket et +ticket-reopen utilisent désormais la même logique.")
    return True


__all__ = ["install"]
