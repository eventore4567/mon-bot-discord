"""Contrat du frontend unique du dashboard (refonte 2026-09, lot 1).

Le document servi sur ``/app`` est assemblé une fois depuis ``web/dashboard_ui`` :
un seul ``<script>`` exécutable, une seule feuille de style, aucune couche historique,
aucune boucle DOM périodique et une navigation courte.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web import dashboard_unified_v2 as unified  # noqa: E402
import sentrix_dashboard_finalizer_v7 as finalizer  # noqa: E402


def _program() -> str:
    match = re.search(r'<script id="sentrix-dashboard-unified-v2">(.*?)</script>', unified.INDEX_HTML, re.S)
    assert match, "programme introuvable"
    return match.group(1)


def test_document_is_a_single_program():
    html = unified.INDEX_HTML
    assert finalizer.verify_single_program(html) == []
    executable = [m for m in re.findall(r"<script([^>]*)>", html) if 'type="application/json"' not in m]
    assert len(executable) == 1
    assert html.count("<style") == 1


def test_assembly_matches_sources():
    """Le module ne fait qu'assembler : toute modification passe par ``dashboard_ui``."""
    assert unified.build_index_html() == unified.INDEX_HTML
    for name in ("index.html", "app.css"):
        assert (unified.UI_DIR / name).exists()
    assert list((unified.UI_DIR / "js").glob("*.js"))


def test_program_syntax_is_valid_javascript(tmp_path):
    node = subprocess.run(["node", "--version"], capture_output=True, text=True)
    if node.returncode != 0:
        pytest.skip("node indisponible")
    target = tmp_path / "program.js"
    target.write_text(_program(), encoding="utf-8")
    result = subprocess.run(["node", "--check", str(target)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_no_periodic_dom_loop():
    program = _program()
    assert "MutationObserver" not in program
    assert "setInterval(loadPublic" not in program
    # Deux minuteurs réseau légers sont autorisés : santé du dashboard et métriques live.
    # Aucun des deux ne relance render() ni une animation quand la réponse est saine.
    intervals = re.findall(r"setInterval\(([^,]+),\s*(\d+)\)", program)
    assert intervals == [
        ("() => dashboardHealthTick()", "30000"),
        ("() => liveTick(false)", "30000"),
    ], intervals
    assert "data-sx-tab" not in program
    assert "Element.prototype.animate" not in program
    # Ces appels sont des transitions ponctuelles : go(), sélection d'un serveur et les
    # deux états initiaux du profil global. Aucun n'est lancé par une boucle périodique.
    assert program.count("render({ navigation: true })") == 4
    assert "el.classList.add('page-enter')" in program and "if (animate)" in program


def test_navigation_is_short_and_grouped():
    program = _program()
    global_nav = re.search(r"const NAV_GLOBAL = \[(.*?)\n\];", program, re.S).group(1)
    server_nav = re.search(r"const NAV_SERVER = \[(.*?)\n\];", program, re.S).group(1)

    assert re.findall(r"\['([a-z]+)', '", global_nav) == ["profile", "servers", "preferences"]
    assert re.findall(r"\['([^']+)', \[\[", global_nav) == ["Mon espace"]

    pages = re.findall(r"\['([a-z]+)', '", server_nav)
    assert pages == [
        "overview", "welcome", "roles", "levels", "economy", "moderation", "security",
        "logs", "tickets", "games", "music", "notifications", "automation", "embeds", "ai",
    ]
    groups = re.findall(r"\['([^']+)', \[\[", server_nav)
    assert groups == [
        "Accueil", "Communauté", "Progression", "Modération", "Jeux", "Musique",
        "Automatisation", "Création & personnalisation",
    ]

    tools = re.search(r"const TOOL_GROUPS = \[(.*?)\n\];", program, re.S).group(1)
    assert len(re.findall(r"\['([a-z]+)', '", tools)) <= 10
    assert "(ancien)" not in program
    assert "MIGRATION_LINKS" in program and "state.developer" in program


def test_legacy_tab_links_are_redirected():
    program = _program()
    legacy = re.search(r"const LEGACY = \{(.*?)\};", program, re.S).group(1)
    for old, target in (("verification", "security"), ("config", "settings"), ("product", "advanced"), ("autoreact", "automation")):
        assert f"{old}: ['{target}'" in legacy
    assert "moderation:" not in legacy


def test_user_facing_strings_use_vouvoiement():
    program = _program()
    for forbidden in ("Choisis ", "Indique ", "Ton serveur", "tu ", "Tu "):
        assert forbidden not in program, forbidden


def test_finalizer_rejects_legacy_layers():
    html = unified.INDEX_HTML.replace("</body>", '<script id="sentrix-dashboard-motion-audio-v27-js">x</script></body>')
    problems = finalizer.verify_single_program(html)
    assert any("motion-audio-v27" in p for p in problems)
    assert any("<script>" in p for p in problems)
