"""Une réponse en erreur ne demande pas son indexation.

Mesuré en production le 2026-09-26 : ``/commands`` rendu en 503 par
l'instance qui ne détient pas le bail HA repartait avec
``X-Robots-Tag: index, follow``. Le handler posait pourtant « noindex » —
trois middlewares d'indexation l'écrasaient ensuite sans regarder le statut.

Ces tests appellent les middlewares eux-mêmes, pas seulement le handler :
c'est ce que le test précédent ne faisait pas, et c'est pour ça qu'il est
passé au vert pendant que la production servait l'inverse.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import MagicMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest
from aiohttp import web

from web import marketing_growth_indexing_v40 as indexing
from web import marketing_growth_v42 as v42
from web import seo_v38

CHEMIN_V40 = "/start"
CHEMIN_V42 = next(iter(v42.PAGES))


def _passer(middlewares, chemin: str, statut: int) -> web.Response:
    """Fait traverser une réponse à la chaîne de middlewares indiquée."""
    requete = MagicMock()
    requete.path = chemin
    requete.app = {}

    async def handler(_requete):
        return web.Response(
            text="<!doctype html><title>x</title>",
            content_type="text/html",
            status=statut,
        )

    async def chaine():
        suivant = handler
        for middleware in reversed(middlewares):
            precedent = suivant

            async def suivant(req, _mw=middleware, _p=precedent):
                return await _mw(req, _p)

        return await suivant(requete)

    return asyncio.run(chaine())


@pytest.mark.parametrize("statut", [404, 429, 500, 502, 503])
def test_indexing_v40_ne_indexe_pas_une_erreur(statut):
    reponse = _passer([indexing.public_growth_indexing], CHEMIN_V40, statut)
    assert reponse.status == statut
    assert reponse.headers["X-Robots-Tag"] == "noindex"


def test_indexing_v40_indexe_toujours_une_page_normale():
    reponse = _passer([indexing.public_growth_indexing], CHEMIN_V40, 200)
    assert reponse.headers["X-Robots-Tag"] == "index, follow"


@pytest.mark.parametrize("statut", [404, 503])
def test_v42_ne_indexe_pas_une_erreur(statut):
    reponse = _passer([v42.indexing_middleware], CHEMIN_V42, statut)
    assert reponse.headers["X-Robots-Tag"] == "noindex"


def test_v42_indexe_toujours_une_page_normale():
    reponse = _passer([v42.indexing_middleware], CHEMIN_V42, 200)
    assert reponse.headers["X-Robots-Tag"] == "index, follow"


@pytest.mark.parametrize("statut", [404, 503])
def test_seo_v38_ne_indexe_pas_une_erreur_sur_la_racine(statut):
    reponse = _passer([seo_v38.indexing_headers], "/", statut)
    assert reponse.headers["X-Robots-Tag"] == "noindex"


def test_seo_v38_indexe_toujours_la_racine():
    reponse = _passer([seo_v38.indexing_headers], "/", 200)
    assert reponse.headers["X-Robots-Tag"] == "index, follow"


# Ordre déduit de la production, pas supposé : seo_v38 considère /start comme
# non public et lui poserait « noindex, nofollow, noarchive », or la production
# sert bien « index, follow » sur /start en 200. Les deux middlewares de
# croissance écrivent donc après lui — ils sont plus à l'extérieur de la pile.
CHAINE = [v42.indexing_middleware, indexing.public_growth_indexing, seo_v38.indexing_headers]


@pytest.mark.parametrize("statut", [404, 503])
def test_la_chaine_complete_ne_indexe_pas_une_erreur(statut):
    """Les trois empilés : aucun ne doit rattraper l'indexation d'une erreur."""
    assert _passer(CHAINE, CHEMIN_V40, statut).headers["X-Robots-Tag"] == "noindex"


def test_la_chaine_complete_indexe_toujours_une_page_normale():
    """Reproduit ce que la production sert réellement sur /start en 200."""
    assert _passer(CHAINE, CHEMIN_V40, 200).headers["X-Robots-Tag"] == "index, follow"
