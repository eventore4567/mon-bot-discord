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


def test_landing_editoriale_structure():
    # 04/11/2026 : refonte « éditoriale » — le vrai produit plutôt qu'une maquette.
    page = _html()
    for marker in (
        'class="wrap hero"', 'class="chat"', 'id="commandes"', 'class="commands"',
        'id="securite"', 'class="facts"', 'id="dashboard"', 'id="faq"', 'class="final"',
    ):
        assert marker in page
    for exemple in ("/moderation ban", "+music saif", "/role menu", "/security strict", "Bannissement effectué"):
        assert exemple in page

def test_landing_sans_tics_de_page_generee():
    """« On voit direct que c'est de l'IA » : plus de halos, dégradés, cubes,
    animations au défilement ni slogan en dégradé."""
    page = _html()
    for tic in (
        "radial-gradient", "linear-gradient", "@keyframes", "backdrop-filter",
        "IntersectionObserver", "requestAnimationFrame", "perspective(", "Moins de chaos",
        "Haute disponibilité", 'class="reveal', "pointermove",
    ):
        assert tic not in page, tic
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


def test_titre_simple_et_lisible():
    page = _html()
    assert "<h1>Le bot qui garde votre serveur Discord en ordre.</h1>" in page
    assert "font-size:clamp(40px,5vw,64px)" in page
    assert "@media(max-width:1180px)" in page

def test_securite_expliquee_concretement():
    page = _html()
    for fait in ("Anti-spam", "Anti-nuke", "Logs lisibles", "noms, catégories, positions et permissions"):
        assert fait in page

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
    assert 'class="skip" href="#main"' in page
    assert 'aria-label="Navigation principale"' in page
    assert 'aria-expanded="false"' in page
    assert 'setAttribute("aria-expanded"' in page

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
