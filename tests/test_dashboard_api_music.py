"""API musique du dashboard : routes et intégration au frontend unifié."""
from __future__ import annotations

import os
from types import SimpleNamespace

from aiohttp import web

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from web import dashboard  # noqa: E402
from web import dashboard_api_music  # noqa: E402
from web import dashboard_unified_v2  # noqa: E402


def test_music_routes_are_registered():
    app = web.Application()
    app["bot"] = SimpleNamespace()
    dashboard_api_music.register(app, dashboard)
    paths = {(route.method, route.resource.canonical) for route in app.router.routes()}
    expected = {
        ("GET", "/api/guilds/{guild_id}/music"),
        ("POST", "/api/guilds/{guild_id}/music/connect"),
        ("POST", "/api/guilds/{guild_id}/music/play"),
        ("POST", "/api/guilds/{guild_id}/music/control"),
        ("POST", "/api/guilds/{guild_id}/music/playlists/create"),
        ("POST", "/api/guilds/{guild_id}/music/playlists/add"),
        ("POST", "/api/guilds/{guild_id}/music/playlists/play"),
        ("DELETE", "/api/guilds/{guild_id}/music/playlists"),
    }
    assert expected <= paths


def test_unified_dashboard_contains_music_page():
    html = dashboard_unified_v2.build_index_html()
    assert "['Musique', [['music', 'Musique']]]" in html
    assert "music: renderMusic" in html
    assert "async function renderMusic()" in html
    assert "/music/connect" in html
    assert "/music/playlists/play" in html
