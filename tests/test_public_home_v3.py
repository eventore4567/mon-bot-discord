from __future__ import annotations

import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from web import brand_avatar_v39, public_home_v3


class _Dashboard:
    @staticmethod
    def _public_url(_request):
        return "https://sentrix.example"

    @staticmethod
    def _invite_url(_bot):
        return "https://discord.com/oauth2/authorize?client_id=123&scope=bot"


def _html() -> str:
    return public_home_v3.render(SimpleNamespace(app={"bot": object()}), _Dashboard)


def test_v3_has_premium_product_structure():
    page = _html()
    for marker in (
        'id="fx"',
        'class="product-shell"',
        'class="hero-proof"',
        'class="wrap status-strip reveal"',
        'class="rail-track"',
        'class="bento stagger"',
        'id="security"',
        'class="tour reveal"',
        'id="automation"',
        'id="ai"',
        'id="faq"',
        'class="wrap final reveal"',
    ):
        assert marker in page


def test_v3_has_interactive_motion_and_reduced_motion_fallback():
    page = _html()
    for marker in (
        "@keyframes floatPanel",
        "@keyframes radar",
        "@keyframes marquee",
        "@keyframes draw",
        "@keyframes paneIn",
        "IntersectionObserver",
        'addEventListener("pointermove"',
        'requestAnimationFrame(tick)',
        'data-pane="pane-security"',
        'data-pane="pane-tickets"',
        'data-pane="pane-economy"',
        'id="progress"',
        'id="pointerRing"',
        # Deux dollars, et sans le commentaire qui dupliquait cette ligne dans
        # le source : le test passait grâce à lui, pas grâce au code.
        'const interactive=$$(".card,.step,.security-box,.tour-screen,.ai-card,.terminal,.status-strip,.workflow-demo")',
        'perspective(1100px) rotateX(',
    ):
        assert marker in page
    assert "@media(prefers-reduced-motion:reduce)" in page


def test_v3_uses_only_real_public_metrics():
    page = _html()
    assert 'fetch("/api/public"' in page
    assert 'id="publicGuilds">—</strong>' in page
    assert 'id="publicMembers">—</strong>' in page
    assert "99.99%" not in page
    assert "100 000 serveurs" not in page
    assert "millions de membres" not in page.lower()


def test_v3_preserves_dashboard_oauth_and_public_links():
    page = _html()
    assert 'href="/app" data-dashboard-entry' in page
    assert 'fetch("/api/me"' in page
    assert 'href="/commands"' in page
    assert 'href="/support"' in page
    assert '<a class="btn ghost" href="/support">Support</a>' in page
    assert 'href="/privacy"' in page
    assert 'href="/terms"' in page
    assert "https://discord.com/oauth2/authorize?client_id=123&amp;scope=bot" in page


def test_home_alias_receives_same_public_branding_as_root():
    assert "/" in brand_avatar_v39._PUBLIC_HTML_PATHS
    assert "/home" in brand_avatar_v39._PUBLIC_HTML_PATHS


def test_dashboard_entry_has_no_horizontal_layout_shift():
    polish = brand_avatar_v39._APP_POLISH
    assert "scrollbar-gutter:stable" in polish
    assert "@keyframes sxAppSide{from{opacity:0}to{opacity:1}}" in polish
    assert "translateX(-12px)" not in polish


def test_v3_hero_headline_stays_compact_and_balanced():
    page = _html()
    assert 'class="hero-line">Moins de chaos.</span>' in page
    assert 'class="accent">Plus de contrôle.</span>' in page
    assert "font-size:clamp(48px,5.2vw,76px)" in page
    assert "@media(max-width:1180px)" in page
    assert "font-size:clamp(38px,10.5vw,52px)" in page


def test_v3_hero_has_richer_capability_cards():
    page = _html()
    assert 'class="hero-proof"' in page
    assert "Sécurité centralisée" in page
    assert "Haute disponibilité" in page
    assert "Configuration directe" in page


def test_v3_home_never_boots_private_guild_data():
    page = _html()
    assert 'fetch("/api/guilds"' not in page
    assert 'fetch("/api/guilds/' not in page
    assert "csrf" not in page.lower()


def test_v3_is_mobile_and_accessibility_aware():
    page = _html()
    assert "@media(max-width:720px)" in page
    assert "@media(max-width:430px)" in page
    assert "@media(max-width:380px)" in page
    assert "@media(pointer:coarse)" in page
    assert 'e.pointerType==="touch"' in page
    assert 'class="skip" href="#main"' in page
    assert 'aria-label="Navigation principale"' in page
    assert 'aria-expanded="false"' in page


def test_v3_javascript_syntax_is_valid(tmp_path: Path):
    node = subprocess.run(["node", "--version"], capture_output=True, text=True)
    if node.returncode != 0:
        pytest.skip("node indisponible")
    page = _html()
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    assert len(scripts) == 1
    target = tmp_path / "public-home-v3.js"
    target.write_text(scripts[0], encoding="utf-8")
    result = subprocess.run(["node", "--check", str(target)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_aucun_selecteur_unique_n_est_parcouru_en_boucle():
    """La panne la plus coûteuse de la landing, mesurée en production.

    ``$`` renvoie un seul élément, ``$$`` un tableau. ``const sections=$(...)``
    suivi de ``sections.forEach`` levait « TypeError: sections.forEach is not
    a function » à la ligne 396, ce qui interrompait tout le reste du script :
    plus de fond animé (le canvas restait à sa taille par défaut de 300×150 et
    n'était jamais dessiné), plus de révélations au scroll, onglets du tour
    inertes, et les statistiques publiques bloquées sur « — ».
    """
    import re

    page = _html()
    noms = set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*\$\(", page))
    fautifs = sorted(n for n in noms if re.search(rf"\b{re.escape(n)}\.forEach\b", page))
    assert not fautifs, f"parcourus alors qu'ils ne sont pas des tableaux : {fautifs}"
