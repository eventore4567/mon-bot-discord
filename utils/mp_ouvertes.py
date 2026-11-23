"""Conversations privées ouvertes à la demande (« mp moi »).

20/11/2026 (#693) : la conversation en message privé a été fermée — SentriX
répond « Je ne discute qu'en serveur ». 22/11/2026 : « fais qu'il puisse MP les
gens : genre ça MP la personne en lui disant "tu voulais me dire quoi" ».

Les deux règles tiennent ensemble : le privé reste fermé par défaut, et ne
s'ouvre que pour la personne qui l'a demandé elle-même dans un serveur, pendant
24 heures. La fenêtre vit en base : un redémarrage ne la referme pas au milieu
d'une conversation.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("bot.mp-ouvertes")

#: Durée d'une conversation privée ouverte par « mp moi ».
DUREE_S = 24 * 3600

SCHEMA = """
CREATE TABLE IF NOT EXISTS sentrix_mp_ouvertes (
    user_id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    expire_at INTEGER NOT NULL
)
"""


async def ouvrir(bot, user_id: int, guild_id: int, *, maintenant: float | None = None) -> None:
    """Ouvre (ou prolonge) la conversation privée de ce membre."""
    fin = int((maintenant if maintenant is not None else time.time()) + DUREE_S)
    await bot.db.execute(SCHEMA)
    await bot.db.execute(
        "INSERT INTO sentrix_mp_ouvertes (user_id, guild_id, expire_at) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET guild_id=excluded.guild_id, expire_at=excluded.expire_at",
        (int(user_id), int(guild_id), fin),
    )


async def est_ouverte(bot, user_id: int, *, maintenant: float | None = None) -> bool:
    """Vrai si ce membre a demandé « mp moi » il y a moins de 24 heures.

    Une base illisible ferme le privé : c'est l'état par défaut, jamais l'inverse.
    """
    return await serveur(bot, user_id, maintenant=maintenant) is not None


async def serveur(bot, user_id: int, *, maintenant: float | None = None) -> int | None:
    """Le serveur où « mp moi » a été demandé, si la conversation est ouverte.

    Revue Codex (PR #712) : sans serveur, le pipeline IA sautait la limite
    quotidienne et l'enregistrement de l'usage — 24 h de conversation privée
    hors quota. La conversation privée est donc rattachée à ce serveur : sa
    limite, ses réglages IA et ses rôles autorisés s'y appliquent.
    """
    try:
        await bot.db.execute(SCHEMA)
        row = await bot.db.fetchone(
            "SELECT guild_id, expire_at FROM sentrix_mp_ouvertes WHERE user_id = ?", (int(user_id),),
        )
    except Exception:  # noqa: BLE001
        logger.warning("Fenêtre de conversation privée illisible pour %s.", user_id, exc_info=True)
        return None
    if row is None:
        return None
    instant = maintenant if maintenant is not None else time.time()
    if int(row["expire_at"] or 0) <= instant:
        return None
    return int(row["guild_id"])
