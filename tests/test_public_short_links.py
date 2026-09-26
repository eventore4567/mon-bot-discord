from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aiohttp import web

from web import marketing_growth_v40


class _Dashboard:
    @staticmethod
    def _invite_url(_bot):
        return "https://discord.com/oauth2/authorize?client_id=1532010415951839252"


def _request():
    return SimpleNamespace(app={"dashboard_module": _Dashboard, "bot": object()})


def _location(handler):
    try:
        asyncio.run(handler(_request()))
    except web.HTTPFound as exc:
        return exc.location
    raise AssertionError("redirect expected")


def test_short_panel_route():
    assert _location(marketing_growth_v40.short_panel) == "/app"


def test_short_docs_route():
    assert _location(marketing_growth_v40.short_docs) == "/commands"


def test_short_support_route():
    assert _location(marketing_growth_v40.short_support) == "/support"


def test_short_add_route_uses_canonical_bot_install_url():
    assert _location(marketing_growth_v40.short_add) == "https://discord.com/oauth2/authorize?client_id=1532010415951839252"
