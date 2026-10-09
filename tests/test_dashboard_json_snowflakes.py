"""Les identifiants Discord quittent l'API du dashboard en texte.

Mesuré le 08/10/2026 : guild_config partait en entiers JSON ; JavaScript lisait
le salon 1419685149431566447 comme 1419685149431566300, et chaque salon ou rôle
configuré s'affichait « Aucun » dans les sélecteurs du dashboard.
"""
from __future__ import annotations

import asyncio
import json

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from web import dashboard

SNOWFLAKE = 1419685149431566447


def _fetch(path: str) -> dict:
    async def handler(_request):
        return web.json_response({
            "settings": {"autorole": SNOWFLAKE, "xp_rate": 5, "enabled": True, "absent": None},
            "social_notifications": [{"role_id": SNOWFLAKE, "id": 3}],
        })

    async def scenario():
        app = web.Application(middlewares=[dashboard.json_snowflakes])
        app.router.add_get(path, handler)
        async with TestClient(TestServer(app)) as client:
            response = await client.get(path)
            return json.loads(await response.text())

    return asyncio.run(scenario())


def test_les_identifiants_de_l_api_sortent_en_texte():
    data = _fetch("/api/guilds/1")
    assert data["settings"]["autorole"] == str(SNOWFLAKE)
    assert data["social_notifications"][0]["role_id"] == str(SNOWFLAKE)


def test_les_petits_nombres_et_booleens_restent_intacts():
    data = _fetch("/api/guilds/1")
    assert data["settings"]["xp_rate"] == 5 and data["settings"]["enabled"] is True
    assert data["settings"]["absent"] is None and data["social_notifications"][0]["id"] == 3


def test_hors_api_rien_ne_change():
    assert _fetch("/health")["settings"]["autorole"] == SNOWFLAKE

