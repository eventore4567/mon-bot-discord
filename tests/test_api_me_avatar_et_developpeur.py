"""/api/me : PP animée embarquée en PNG, et `developer` transmis au client."""
import asyncio
import json
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from web import dashboard_user_avatar_v46 as module

GIF = "https://cdn.discordapp.com/avatars/1/a_abc.gif?size=128"


def test_pp_animee_embarquee_en_png():
    session = {"user": {"id": "1", "avatar_url": GIF}}
    url = asyncio.run(module._discord_avatar_url(None, session))
    assert url == "https://cdn.discordapp.com/avatars/1/a_abc.png?size=128"


def _reponse(monkeypatch, proprietaire):
    async def is_owner(_user):
        return proprietaire

    async def pas_de_pp(_request, _session):
        return None

    session = {"user": {"id": "42", "username": "jayden"}, "csrf": "jeton"}
    dashboard = SimpleNamespace(_require_session=lambda _request: (session, None))
    app = web.Application()
    app["dashboard_module"] = dashboard
    app["bot"] = SimpleNamespace(is_owner=is_owner)
    monkeypatch.setattr(module, "_avatar_data_uri", pas_de_pp)
    reponse = asyncio.run(module.handle_me_with_embedded_avatar(make_mocked_request("GET", "/api/me", app=app)))
    return json.loads(reponse.body)


def test_proprietaire_recoit_developer(monkeypatch):
    assert _reponse(monkeypatch, True)["developer"] is True


def test_admin_ordinaire_ne_recoit_pas_developer(monkeypatch):
    corps = _reponse(monkeypatch, False)
    assert corps["developer"] is False
    assert corps["csrf"] == "jeton"
