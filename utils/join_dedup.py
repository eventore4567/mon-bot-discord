"""Un seul système de bienvenue par arrivée, même en HA active/passive.

Plusieurs fonctionnalités indépendantes (bienvenue standard de Setup, « smart
welcome » de +sentrixpro, onboarding avec choix de rôle de la Suite
Engagement) peuvent chacune vouloir annoncer l'arrivée d'un membre. Sans
coordination entre elles, elles s'exécutent TOUTES sur le même événement —
c'est la cause des messages de bienvenue en double, indépendamment de tout
nettoyage a posteriori.

``reclamer(...)`` pose une clé Redis partagée (SET ... NX EX) : seul le
PREMIER appelant obtient True et a le droit d'envoyer un message. Les autres
reçoivent False et se taisent, purement et simplement. La clé passe par
``storage_key()`` — le même helper que le lease de failover — donc elle est
partagée entre le primary et le standby : même lors d'une bascule où les deux
processus sont brièvement connectés à Discord en même temps, un seul des deux
gagne la course, et l'autre ne double-annonce jamais.

Sans Redis configuré (dev local, ou HA désactivé), un repli en mémoire du
processus protège au moins contre plusieurs producteurs DANS LE MÊME
processus — le cas le plus fréquent en dehors d'une bascule HA.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from utils.instance_identity import storage_key

logger = logging.getLogger("bot.join-dedup")

try:
    import redis.asyncio as redis_async  # type: ignore
except Exception:  # pragma: no cover - dépendance contrôlée au déploiement
    redis_async = None

# Large marge sur la durée d'un envoi (carte + rôle) et sur la fenêtre d'une
# bascule HA (le lease de failover lui-même tourne autour de 15-180s).
_TTL_SECONDS = 60

_redis_client: Any = None
_redis_tentative_faite = False
_memoire_locale: dict[str, float] = {}


def _redis_url() -> str:
    return (
        os.getenv("SENTRIX_FAILOVER_REDIS_URL")
        or os.getenv("SENTRIX_REDIS_URL")
        or os.getenv("REDIS_URL")
        or ""
    ).strip()


async def _obtenir_redis():
    global _redis_client, _redis_tentative_faite
    if _redis_client is not None:
        return _redis_client
    if _redis_tentative_faite:
        # Un seul essai par processus : si Redis est down, retenter à chaque
        # arrivée de membre ajouterait une latence de connexion à chaque join
        # sans jamais réussir avant le prochain redémarrage.
        return None
    _redis_tentative_faite = True
    url = _redis_url()
    if not url or redis_async is None:
        return None
    try:
        client = redis_async.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        await client.ping()
    except Exception:
        logger.warning("join_dedup : Redis indisponible, repli sur la mémoire locale.")
        return None
    _redis_client = client
    return client


def _nettoyer_memoire_locale() -> None:
    limite = time.monotonic() - _TTL_SECONDS
    expirees = [cle for cle, posee_a in _memoire_locale.items() if posee_a < limite]
    for cle in expirees:
        _memoire_locale.pop(cle, None)


async def reclamer(bot: Any, guild_id: int, member_id: int, event: str = "join") -> bool:
    """True si CET appel est le premier à réclamer cet événement, False sinon.

    ``bot`` n'est pas utilisé directement (aucune dépendance à une connexion
    Redis déjà ouverte ailleurs) mais reste au signature pour que l'appelant
    n'ait jamais besoin de deviner ce qui est réellement nécessaire.
    """
    del bot
    cle = storage_key(f"join-event:{event}:{int(guild_id)}:{int(member_id)}")

    redis_client = await _obtenir_redis()
    if redis_client is not None:
        try:
            posee = await redis_client.set(cle, "1", nx=True, ex=_TTL_SECONDS)
            return bool(posee)
        except Exception:
            logger.warning("join_dedup : écriture Redis impossible, repli sur la mémoire locale.")

    _nettoyer_memoire_locale()
    if cle in _memoire_locale:
        return False
    _memoire_locale[cle] = time.monotonic()
    return True
