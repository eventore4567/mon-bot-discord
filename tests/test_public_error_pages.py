"""Pages d'erreur SentriX : une vraie page, sans casser les API.

Mesuré en production le 2026-09-26 : une route inexistante renvoyait
« 404: Not Found », quatorze octets de texte brut — le défaut d'aiohttp —
alors que le reste du site public venait d'être refait.

Le risque en corrigeant ça est de trop intercepter : si le middleware
transformait aussi les erreurs d'API en HTML, le dashboard recevrait une page
web là où il attend du JSON et casserait sans bruit. C'est ce que ces tests
verrouillent en priorité.
"""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from web import public_error_pages_v1 as pages


def _app() -> web.Application:
    app = web.Application(middlewares=[pages.pages_erreur])

    async def ok(_request):
        return web.Response(text="ok")

    async def api_absent(_request):
        raise web.HTTPNotFound(text='{"error":"nope"}', content_type="application/json")

    async def api_erreur(_request):
        return web.json_response({"error": "boom"}, status=500)

    async def refuse(_request):
        raise web.HTTPForbidden()

    app.router.add_get("/", ok)
    app.router.add_get("/health", ok)
    app.router.add_get("/api/manquant", api_absent)
    app.router.add_get("/api/casse", api_erreur)
    app.router.add_get("/prive", refuse)
    return app


def _get(chemin: str, accept: str = "text/html"):
    async def scenario():
        async with TestClient(TestServer(_app())) as client:
            reponse = await client.get(chemin, headers={"Accept": accept})
            return reponse.status, reponse.content_type, await reponse.text()

    return asyncio.run(scenario())


# ----------------------------------------------------------------- navigateur

def test_une_route_inconnue_rend_une_vraie_page():
    statut, type_contenu, corps = _get("/route-qui-nexiste-pas")
    assert statut == 404
    assert type_contenu == "text/html"
    assert len(corps) > 2000, "la page doit être une vraie page, pas un texte court"
    assert "SentriX" in corps


def test_la_page_dit_quoi_faire_et_pas_seulement_ce_qui_a_raté():
    """« Not Found » ne nomme ni la cause ni la sortie."""
    _statut, _type, corps = _get("/inconnu")
    assert "Page introuvable" in corps
    for lien in ('href="/"', 'href="/docs"', 'href="/app"', 'href="/support"'):
        assert lien in corps, f"lien manquant : {lien}"


def test_la_page_rappelle_l_adresse_demandee():
    _statut, _type, corps = _get("/chemin/tres/precis")
    assert "/chemin/tres/precis" in corps


def test_le_code_de_statut_n_est_jamais_modifie():
    """Transformer un 404 en 200 tromperait les moteurs de recherche."""
    assert _get("/inconnu")[0] == 404
    assert _get("/prive")[0] == 403


def test_un_403_a_son_propre_message():
    _statut, _type, corps = _get("/prive")
    assert "Accès refusé" in corps
    assert "Discord" in corps


def test_la_page_d_erreur_n_est_pas_indexee():
    _statut, _type, corps = _get("/inconnu")
    assert 'name="robots" content="noindex' in corps


# ------------------------------------------------------------------ API intacte

def test_une_erreur_d_api_reste_du_json():
    """Le dashboard attend un objet : lui rendre du HTML le casserait en silence."""
    statut, type_contenu, corps = _get("/api/manquant", accept="application/json")
    assert statut == 404
    assert type_contenu == "application/json"
    assert "<html" not in corps


def test_une_erreur_d_api_reste_du_json_meme_pour_un_navigateur():
    """Ouvrir une URL d'API dans un onglet ne doit pas changer sa réponse."""
    statut, type_contenu, corps = _get("/api/casse", accept="text/html")
    assert statut == 500
    assert type_contenu == "application/json"
    assert "<html" not in corps


def test_health_reste_intact():
    """Railway lit cette route pour décider si le service est vivant."""
    statut, _type, corps = _get("/health")
    assert statut == 200
    assert corps == "ok"


def test_un_client_non_navigateur_garde_une_reponse_courte():
    statut, type_contenu, corps = _get("/inconnu", accept="application/json")
    assert statut == 404
    assert "<html" not in corps


# ------------------------------------------------------------------- réponses OK

def test_une_reponse_normale_traverse_sans_etre_touchee():
    statut, _type, corps = _get("/")
    assert statut == 200 and corps == "ok"


# ------------------------------------------------------------------- rendu

@pytest.mark.parametrize("statut", [403, 404, 429, 500, 502, 503])
def test_chaque_code_connu_a_son_texte(statut):
    corps = pages.rendre(statut, "/x")
    assert str(statut) in corps
    assert "Erreur\n" not in corps, f"{statut} retombe sur le message générique"


def test_un_code_inconnu_reste_lisible():
    corps = pages.rendre(418, "/x")
    assert "418" in corps and "SentriX" in corps


def test_la_page_respecte_le_mouvement_reduit():
    corps = pages.rendre(404, "/x")
    assert "prefers-reduced-motion" in corps


def test_la_page_porte_le_fond_anime_partage():
    """Une identité unique : la page d'erreur utilise le même moteur que le reste."""
    corps = pages.rendre(404, "/x")
    assert 'id="sxfx"' in corps
    assert "requestAnimationFrame" in corps


def test_l_adresse_affichee_est_echappee():
    """Un chemin est une entrée utilisateur : l'injecter brut serait une faille."""
    corps = pages.rendre(404, '/<script>alert(1)</script>')
    assert "<script>alert(1)</script>" not in corps
    assert "&lt;script&gt;" in corps
