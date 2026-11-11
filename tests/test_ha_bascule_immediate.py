"""11/11/2026 : la bascule attendait un sondage pour rien.

« Pourquoi 2 secondes ? » — parce que l'instance en attente demandait à Redis si
le bail était libre toutes les 2 secondes, et qu'au pire elle ratait la
libération d'un cheveu. Pendant une mise à jour, c'était 2 secondes de bot
muet, à chaque déploiement, pour une information que le leader sortant
connaissait déjà.

Il l'annonce désormais sur un canal Redis, et son remplaçant repart aussitôt.
L'annonce reste un RACCOURCI : si elle se perd, si personne n'écoute, ou si le
leader meurt sans l'envoyer, le sondage de secours reprend la main comme avant.
C'est ce que ces tests verrouillent — le gain ET le filet.
"""
from __future__ import annotations

import asyncio
import os
import time

import pytest

os.environ.setdefault("DISCORD_TOKEN", "x")

from utils.failover import SentriXFailoverCoordinator  # noqa: E402


class _RedisAvecCanal:
    """Redis minimal : SET NX/EX, GET, le script Lua de libération et PUBLISH."""

    def __init__(self):
        self.donnees: dict[str, str] = {}
        self.annonces: list[tuple[str, str]] = []

    async def set(self, cle, valeur, nx=False, ex=None):
        if nx and cle in self.donnees:
            return None
        self.donnees[cle] = valeur
        return True

    async def get(self, cle):
        return self.donnees.get(cle)

    async def eval(self, script, _n, cle, proprietaire, *args):
        if self.donnees.get(cle) != proprietaire:
            return 0
        if "del" in script:
            self.donnees.pop(cle, None)
        return 1

    async def publish(self, canal, message):
        self.annonces.append((canal, message))
        return 1

    async def ping(self):
        return True

    async def aclose(self):
        return None


def _coordinateur(service: str, redis, role: str = "primary") -> SentriXFailoverCoordinator:
    coord = SentriXFailoverCoordinator()
    coord.enabled = True
    coord.redis_url = "redis://faux"
    coord.role = role
    coord.service_id = service
    coord.state = "starting"
    coord._redis = redis
    return coord


@pytest.mark.asyncio
async def test_le_leader_qui_part_annonce_sa_sortie():
    redis = _RedisAvecCanal()
    leader = _coordinateur("sortant", redis)
    assert await leader._try_acquire()
    assert await leader.release()

    assert redis.annonces == [(leader.canal_liberation, leader.owner_id)]


@pytest.mark.asyncio
async def test_une_annonce_perdue_ne_casse_rien():
    """L'annonce est un raccourci : sans elle, la libération reste une libération."""

    class _SansPublish(_RedisAvecCanal):
        async def publish(self, canal, message):
            raise RuntimeError("canal injoignable")

    redis = _SansPublish()
    leader = _coordinateur("sortant", redis)
    assert await leader._try_acquire()
    assert await leader.release() is True
    assert leader.lock_key not in redis.donnees


@pytest.mark.asyncio
async def test_l_annonce_reveille_l_attente_sans_attendre_le_sondage():
    coord = _coordinateur("attente", _RedisAvecCanal())
    coord.poll_seconds = 30  # Sans l'annonce, l'attente durerait 30 secondes.

    debut = time.monotonic()
    reveil = asyncio.get_running_loop().call_later(0.05, coord._reveil.set)
    await coord._attendre_le_prochain_essai()
    reveil.cancel()

    assert time.monotonic() - debut < 1.0


@pytest.mark.asyncio
async def test_sans_annonce_le_sondage_reste_le_filet():
    coord = _coordinateur("attente", _RedisAvecCanal())
    coord.poll_seconds = 0.2  # Personne n'annonce : on repart au sondage suivant.

    debut = time.monotonic()
    await coord._attendre_le_prochain_essai()
    ecoule = time.monotonic() - debut

    assert 0.15 <= ecoule < 1.5


@pytest.mark.asyncio
async def test_l_arret_debloque_l_attente_immediatement():
    """SIGTERM sur une instance passive ne doit pas attendre le sondage non plus."""
    coord = _coordinateur("attente", _RedisAvecCanal())
    coord.poll_seconds = 30

    debut = time.monotonic()
    asyncio.get_running_loop().call_later(0.05, coord.demander_arret)
    await coord._attendre_le_prochain_essai()

    assert time.monotonic() - debut < 1.0


@pytest.mark.asyncio
async def test_une_annonce_ne_fait_jamais_deux_leaders():
    """Réessayer plus tôt ne change que le MOMENT : _try_acquire reste un SET NX."""
    redis = _RedisAvecCanal()
    tenant = _coordinateur("tenant", redis)
    pretendant = _coordinateur("pretendant", redis)

    assert await tenant._try_acquire()
    # Le prétendant est réveillé par une annonce, alors que le bail est encore pris.
    pretendant._reveil.set()
    await pretendant._attendre_le_prochain_essai()
    assert await pretendant._try_acquire() is False
    assert redis.donnees[tenant.lock_key] == tenant.owner_id
