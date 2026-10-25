"""Un callback OAuth rejoué par un navigateur déjà connecté ramène au dashboard."""
import asyncio
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from web import dashboard

URL = "/oauth/callback?code=abc&state=1792936688.sig"


def _requete():
    app = web.Application()
    app["oauth_states"] = {}
    return make_mocked_request("GET", URL, app=app)


def test_callback_rejoue_avec_session_revient_au_dashboard(monkeypatch):
    monkeypatch.setattr(dashboard, "_session", lambda _request: {"user_id": 1})
    with pytest.raises(web.HTTPFound) as redirection:
        asyncio.run(dashboard.handle_callback(_requete()))
    assert redirection.value.location == "/app"


def test_callback_sans_cookie_ni_session_reste_refuse(monkeypatch):
    monkeypatch.setattr(dashboard, "_session", lambda _request: None)
    reponse = asyncio.run(dashboard.handle_callback(_requete()))
    assert reponse.status == 403
