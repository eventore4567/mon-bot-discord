"""Régressions de lisibilité du dashboard normal et de l'accueil public SentriX.

Le polissage est purement éditorial / CSS. Toutes les actions restent servies par le
programme dashboard unifié existant, sans modification des permissions ou APIs.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from web import dashboard_unified_v2, public_home_v3

ROOT = Path(__file__).resolve().parents[1]


class Dashboard:
    @staticmethod
    def _public_url(_request):
        return "https://sentrix.example"

    @staticmethod
    def _invite_url(_bot):
        return "https://discord.com/oauth2/authorize?client_id=123&scope=bot"


def page():
    return public_home_v3.render(SimpleNamespace(app={"bot": object()}), Dashboard)


def test_public_site_preserves_real_actions_and_has_polished_copy():
    html = page()
    assert "Protégez votre communauté, organisez votre staff" in html
    assert "Vos questions, nos réponses." in html
    assert 'href="/app" data-dashboard-entry' in html
    assert 'href="__INVITE__"' not in html
    assert 'href="/docs"' in html
    assert 'href="/support"' in html
    assert 'href="/premium"' in html
    assert "moins de chaos" in html.lower()
    assert 'href="#main"' in html


def test_public_site_aligns_cards_and_mobile_typography():
    html = page()
    for required in (
        "SentriX Normal V1",
        ".hero-proof{gap:10px;",
        ".proof span{font-size:10.5px;",
        ".faq-list summary{padding:15px 0;font-size:13px",
        "@media(max-width:720px)",
        "@media(max-width:430px)",
        "@media(prefers-reduced-motion:reduce)",
    ):
        assert required in html


def test_unified_dashboard_keeps_one_script_one_stylesheet_and_original_routes():
    html = dashboard_unified_v2.INDEX_HTML
    assert html.count('id="sentrix-dashboard-unified-v2"') == 1
    assert html.count("<style>") == 1
    assert html.count('id="content"') == 1
    assert "async function render({ navigation = false } = {})" in html
    assert "function renderNav()" in html
    assert "'/api/me'" in html
    assert "'/api/guilds'" in html
    assert 'href="/premium"' in html


def test_default_design_improves_spacing_without_overriding_compact_density():
    css = (ROOT / "web" / "dashboard_ui" / "app.css").read_text(encoding="utf-8")
    assert "SentriX Normal V1" in css
    assert 'html:not([data-density="compact"]) .workspace{' in css
    assert ".module-card .toolbar{margin-top:auto" in css
    assert ".row-actions{max-width:100%;flex-wrap:wrap" in css
    assert "@media(max-width:700px)" in css
    assert "prefers-reduced-motion:reduce" in css


def test_page_has_no_fake_purchase_and_free_modules_still_listed():
    html = dashboard_unified_v2.INDEX_HTML
    for key in ("Accueil & Départs", "Niveaux", "Économie", "Sécurité", "Tickets", "Logs", "Musique"):
        assert key in html
    assert "stripe.com" not in html.lower()
    assert "checkout.session" not in html.lower()
