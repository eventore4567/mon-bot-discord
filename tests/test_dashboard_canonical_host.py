"""OAuth sur l'hôte canonique.

Le cookie de state et le cookie de session sont liés à l'hôte du navigateur, alors que
Discord renvoie toujours sur DASHBOARD_PUBLIC_URL. Un login commencé sur un autre hôte
(domaine du standby) échouait donc systématiquement avec « Connexion impossible » : le
callback arrivait sans cookie. /login et /app ramènent maintenant sur l'hôte canonique.
"""
from __future__ import annotations

import asyncio
import os

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import config  # noqa: E402
from web import dashboard  # noqa: E402


@pytest.fixture
def canonical(monkeypatch):
    monkeypatch.setattr(config, "DASHBOARD_PUBLIC_URL", "https://mon-bot-discord-production-8944.up.railway.app")
    yield


def test_other_host_is_redirected_to_canonical_host(canonical):
    req = make_mocked_request("GET", "/login?next=%2Fapp", headers={"Host": "sentrix-standby-production.up.railway.app"})
    redirect = dashboard._canonical_redirect(req)
    assert isinstance(redirect, web.HTTPFound)
    assert redirect.location in ("https://mon-bot-discord-production-8944.up.railway.app/login?next=%2Fapp", "https://mon-bot-discord-production-8944.up.railway.app/login?next=/app")


def test_forwarded_host_from_ha_proxy_is_used(canonical):
    # Requête relayée par le proxy HA : l'hôte interne ne compte pas, seul l'hôte du navigateur.
    req = make_mocked_request("GET", "/app", headers={"Host": "mon-bot-discord.railway.internal:8080", "X-Forwarded-Host": "mon-bot-discord-production-8944.up.railway.app"})
    assert dashboard._canonical_redirect(req) is None
    req = make_mocked_request("GET", "/app?tab=welcome", headers={"Host": "sentrix-standby.railway.internal:8080", "X-Forwarded-Host": "sentrix-standby-production.up.railway.app"})
    assert dashboard._canonical_redirect(req).location.endswith("/app?tab=welcome")


def test_canonical_host_itself_is_never_redirected(canonical):
    req = make_mocked_request("GET", "/login", headers={"Host": "mon-bot-discord-production-8944.up.railway.app"})
    assert dashboard._canonical_redirect(req) is None
    req = make_mocked_request("GET", "/login", headers={"Host": "MON-BOT-DISCORD-PRODUCTION-8944.up.railway.app"})
    assert dashboard._canonical_redirect(req) is None


def test_without_public_url_nothing_changes(monkeypatch):
    monkeypatch.setattr(config, "DASHBOARD_PUBLIC_URL", "")
    req = make_mocked_request("GET", "/login", headers={"Host": "127.0.0.1:8992"})
    assert dashboard._canonical_redirect(req) is None


def test_loopback_hosts_are_never_redirected(canonical):
    for host in ("127.0.0.1:8992", "localhost:8080", "[::1]:8080"):
        req = make_mocked_request("GET", "/app", headers={"Host": host})
        assert dashboard._canonical_redirect(req) is None, host


def test_middleware_only_touches_app_and_login(canonical):
    async def handler(request):
        return web.Response(text="ok")

    async def run(path, method="GET"):
        req = make_mocked_request(method, path, headers={"Host": "sentrix-standby-production.up.railway.app"})
        try:
            return await dashboard.canonical_host(req, handler)
        except web.HTTPFound as redirect:
            return redirect

    assert isinstance(asyncio.run(run("/app")), web.HTTPFound)
    assert isinstance(asyncio.run(run("/login")), web.HTTPFound)
    assert asyncio.run(run("/health")).text == "ok"
    assert asyncio.run(run("/api/guilds")).text == "ok"
    assert asyncio.run(run("/oauth/callback")).text == "ok"
    assert asyncio.run(run("/logout", "POST")).text == "ok"


def test_callback_refuses_without_state_cookie(canonical):
    """Reproduction du bug : state connu de l'instance mais cookie absent → 403, jamais 500."""
    app = {"oauth_states": {"abc": 9999999999.0}, "bot": None}
    req = make_mocked_request("GET", "/oauth/callback?state=abc&code=x", headers={"Host": "mon-bot-discord-production-8944.up.railway.app"}, app=app)
    response = asyncio.run(dashboard.handle_callback(req))
    assert response.status == 403
    assert "Connexion impossible" in response.text
