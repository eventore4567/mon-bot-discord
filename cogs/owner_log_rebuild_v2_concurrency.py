"""Protection de concurrence pour le rebuild V2.

Si une autre instance reprend une ou plusieurs routes pendant le reset, on ne peut plus
savoir de façon atomique quels nouveaux salons elle utilise déjà. La stratégie sûre est
donc de ne rien supprimer dans ce cas. Un salon orphelin est préférable à une route active
cassée ; les anciens salons ne sont retirés que par l'exécution qui possède encore les 8
routes après les deux contrôles de stabilité.
"""
from __future__ import annotations

import logging

from . import owner_log_rebuild_v2 as v2

logger = logging.getLogger("bot.owner-log-rebuild-v2-concurrency")


async def preserve_on_lost_ownership(channels, categories, *, reason: str) -> None:
    logger.warning(
        "Nettoyage destructif ignoré après perte de propriété des routes (%s) : %s salon(s), %s catégorie(s) préservés.",
        reason,
        len(channels),
        len(categories),
    )


def install() -> None:
    v2._cleanup_created = preserve_on_lost_ownership
