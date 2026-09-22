"""Contrats isolés du profil et du centre de modération du dashboard."""
from __future__ import annotations

import os
from types import SimpleNamespace

from aiohttp import web

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from web import dashboard  # noqa: E402
from web import dashboard_api_moderation as moderation  # noqa: E402
from web import dashboard_api_profile as profile  # noqa: E402


def _paths(register):
    app = web.Application()
    app["bot"] = SimpleNamespace(db=None)
    register(app, dashboard)
    return {(route.method, route.resource.canonical) for route in app.router.routes()}


def test_moderation_routes_are_registered():
    assert {
        ("GET", "/api/guilds/{guild_id}/moderation/members"),
        ("GET", "/api/guilds/{guild_id}/moderation/members/{user_id}"),
        ("POST", "/api/guilds/{guild_id}/moderation/actions"),
    } <= _paths(moderation.register)


def test_profile_routes_are_registered():
    assert {
        ("GET", "/api/guilds/{guild_id}/profile/me"),
        ("PUT", "/api/guilds/{guild_id}/profile/me"),
    } <= _paths(profile.register)


def test_profile_background_requires_https_without_credentials():
    assert profile._https_url("") is True
    assert profile._https_url("https://cdn.example.test/card.png") is True
    assert profile._https_url("http://cdn.example.test/card.png") is False
    assert profile._https_url("https://user:pass@example.test/card.png") is False


def test_moderation_action_contract_is_explicit():
    assert set(moderation._ACTION_META) == {"warn", "mute", "kick", "ban"}
    assert moderation._ACTION_META["ban"][2] == "ban_members"
    assert moderation._ACTION_META["mute"][2] == "moderate_members"
