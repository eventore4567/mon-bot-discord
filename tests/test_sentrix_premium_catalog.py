"""Régression du catalogue Premium indépendant du dashboard historique."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web

MODULE_PATH = Path(__file__).resolve().parents[1] / "web" / "sentrix_premium_catalog.py"
spec = importlib.util.spec_from_file_location("sentrix_premium_catalog_direct", MODULE_PATH)
assert spec and spec.loader
premium = importlib.util.module_from_spec(spec)
spec.loader.exec_module(premium)


def test_catalog_displays_offers_with_no_active_purchase():
    html = premium.PAGE_HTML
    for expected in (
        "SentriX Free", "SentriX Premium", "SentriX Premium+",
        "0 €", "2,99 €", "5,99 €",
        "Aucun abonnement, prélèvement ou paiement",
        "sans sacrifier le gratuit", "Les fonctionnalités actuelles restent disponibles",
        'href="/app"',
    ):
        assert expected in html
    assert "<form" not in html.lower()
    assert "checkout" not in html.lower()
    assert "stripe" not in html.lower()
    assert "paypal" not in html.lower()
    assert "card-number" not in html.lower()
    assert "viewport" in html
    assert "@media(max-width:640px)" in html
    assert "prefers-reduced-motion" in html


def test_dashboard_links_added_once_without_overwriting_existing_navigation():
    original = """<html><head></head><body><section id="landing">
        <a class="btn" id="inviteButton" href="/invite">Ajouter SentriX</a>
        </section><aside><nav class="nav" id="navigation">
        <button data-tab="general">Général</button><button data-tab="logs">Logs</button>
        </nav></aside><script>const renderTab=()=>{};</script></body></html>"""
    first = premium.inject_premium_link(original)
    second = premium.inject_premium_link(first)
    assert second == first
    assert first.count("data-sentrix-premium-link") == 1
    assert first.count('href="/premium"') == 2
    assert 'data-tab="general"' in first
    assert 'data-tab="logs"' in first
    assert 'const renderTab=()=>{}' in first
    assert first.index('data-tab="logs"') < first.index("data-sentrix-premium-link") < first.index("</nav>")


def test_catalog_installer_only_adds_public_get_and_preserves_existing_routes():
    def original_build(_bot):
        app = web.Application()
        app.router.add_get("/app", lambda _r: web.Response(text="OK"))
        return app

    dashboard = SimpleNamespace(build_app=original_build, INDEX_HTML='<html><head></head><body></body></html>')
    premium.install(dashboard)
    app = dashboard.build_app(None)
    routes = [(route.method, route.resource.canonical) for route in app.router.routes()]
    assert ("GET", "/app") in routes
    assert ("GET", "/premium") in routes
    assert not any(route for route in routes if route[1] == "/premium" and route[0] in ("POST", "PUT", "DELETE"))


@pytest.mark.asyncio
async def test_catalog_is_read_only_with_safe_response_headers():
    response = await premium.handle_premium_catalog(None)
    assert response.status == 200
    assert response.content_type == "text/html"
    assert "noindex" in response.headers["X-Robots-Tag"]
    assert "no-store" in response.headers["Cache-Control"]
    assert "form-action 'none'" in response.headers["Content-Security-Policy"]
    assert "SentriX Premium" in response.text
