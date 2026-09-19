"""API Bienvenue du dashboard : même moteur que le bouton « Bienvenue » de /setup.

Les trois routes réutilisent ``cogs.setup_v2_completion`` (présentation, sauvegarde, test) :
le dashboard ne possède aucune logique propre de bienvenue.
"""
from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace
from unittest import mock

import pytest
from aiohttp.streams import StreamReader
from aiohttp.test_utils import make_mocked_request

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from web import dashboard  # noqa: E402


class _App(dict):
    pass


def _request(method: str, path: str, payload=None, *, member=None, bot_db=None):
    guild = SimpleNamespace(id=1, name="Serveur", get_member=lambda uid: member)
    body = json.dumps(payload or {}).encode() if payload is not None else b""
    app = _App()
    app["bot"] = SimpleNamespace(db=bot_db)
    app["write_limits"] = {}
    reader = StreamReader(mock.Mock(_reading_paused=False), 2 ** 16, loop=asyncio.new_event_loop())
    reader.feed_data(body)
    reader.feed_eof()
    req = make_mocked_request(method, path, match_info={"guild_id": "1"}, app=app, payload=reader)
    return req, guild


@pytest.fixture
def api(monkeypatch):
    session = {"user": {"id": "42", "username": "Owner"}, "csrf": "x"}
    saved = {}
    calls = {"test": 0}

    async def manageable(request, guild_id):
        return session, request._sentrix_guild, None

    monkeypatch.setattr(dashboard, "_manageable_guild", manageable)
    monkeypatch.setattr(dashboard, "_require_csrf", lambda request, session: None)

    class FakeWelcome:
        WELCOME_DEFAULT_TITLE = "Bienvenue sur {server}"
        WELCOME_DEFAULT_TEXT = "Bienvenue {member} !"

        @staticmethod
        async def _welcome_presentation(bot, guild_id):
            return saved.get(guild_id, {"title": "Bienvenue sur {server}", "show_avatar": True, "show_member_count": True})

        @staticmethod
        async def _save_welcome_presentation(bot, guild_id, *, title, show_avatar, show_member_count, actor_id, mode=None):
            saved[guild_id] = {"title": title, "show_avatar": show_avatar, "show_member_count": show_member_count, "actor": actor_id, "mode": mode}

        @staticmethod
        async def _send_welcome(bot, member, *, test=False):
            calls["test"] += 1
            assert test is True
            return True, "Test envoyé dans #bienvenue."

    async def module():
        return FakeWelcome

    monkeypatch.setattr(dashboard, "_welcome_module", module)
    return saved, calls


def _run(handler, req, guild):
    req._sentrix_guild = guild
    resp = asyncio.run(handler(req))
    return resp.status, json.loads(resp.text)


def test_get_returns_presentation_and_real_variables(api):
    req, guild = _request("GET", "/api/guilds/1/welcome")
    status, data = _run(dashboard.handle_welcome_get, req, guild)
    assert status == 200
    assert data["title"] == "Bienvenue sur {server}"
    assert data["variables"] == ["{member}", "{username}", "{display_name}", "{server}", "{member_count}"]


def test_put_saves_through_the_cog_function(api):
    saved, _ = api
    req, guild = _request("PUT", "/api/guilds/1/welcome", {"title": "Salut {display_name}", "show_avatar": False, "show_member_count": True, "mode": "text"})
    status, data = _run(dashboard.handle_welcome_put, req, guild)
    assert status == 200 and data["ok"] is True
    assert saved[1] == {"title": "Salut {display_name}", "show_avatar": False, "show_member_count": True, "actor": 42, "mode": "text"}
    # Valeur inconnue → embed (jamais d'état intermédiaire).
    req, guild = _request("PUT", "/api/guilds/1/welcome", {"title": "x", "mode": "n'importe quoi"})
    _run(dashboard.handle_welcome_put, req, guild)
    assert saved[1]["mode"] == "embed"


def test_test_send_requires_a_visible_member(api):
    _, calls = api
    req, guild = _request("POST", "/api/guilds/1/welcome/test", {}, member=None)
    status, data = _run(dashboard.handle_welcome_test, req, guild)
    assert status == 409 and calls["test"] == 0

    member = SimpleNamespace(id=42)
    req, guild = _request("POST", "/api/guilds/1/welcome/test", {}, member=member)
    status, data = _run(dashboard.handle_welcome_test, req, guild)
    assert status == 200 and calls["test"] == 1
    assert "Test envoyé" in data["message"]
