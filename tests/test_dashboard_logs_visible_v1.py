"""Contrats du vrai centre des logs, assemblé et servi dans /app.

Les tests portent sur l'UI canonique, pas sur un dessin séparé.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from web import dashboard_unified_v2 as unified


ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web" / "dashboard_ui" / "js" / "37_logs.js"
CSS = ROOT / "web" / "dashboard_ui" / "app.css"


def test_logs_new_ui_is_really_bundled_in_app():
    html = unified.INDEX_HTML
    assert 'Votre centre des logs' in html
    assert 'data-log-count="active"' in html
    assert 'data-log-count="issue"' in html
    assert 'data-log-count="off"' in html
    assert 'id="logRouteSearch"' in html
    assert 'data-log-filter="active"' in html
    assert 'data-log-filter="issue"' in html
    assert 'data-log-filter="off"' in html
    assert 'data-log-preview="' in html
    assert 'Exemple fictif' in html
    assert 'Aucun message n\'est envoyé au serveur.' in html
    assert 'data-log-channel="' in html
    assert 'data-log-enabled="' in html


def test_settings_use_existing_real_api_and_report_failures():
    source = JS.read_text(encoding="utf-8")
    assert "gget('/logs/config')" in source
    assert "gpost('/logs/config'" in source
    assert "invalidate('log-config-v2')" in source
    assert "enabled.checked = Boolean(previous.enabled)" in source
    assert "channel.value = String(previous.channel_id || '')" in source
    assert "feedback.textContent = 'Non enregistré'" in source
    assert "card.classList.remove('log-route-saving')" in source
    assert "data-log-event" in source, "Les interrupteurs d'événements existants doivent rester fonctionnels"


def test_sample_is_clearly_marked_and_escapes_server_names():
    source = JS.read_text(encoding="utf-8")
    assert "esc(route.label)" in source
    assert "esc(route.key)" in source
    assert "data-log-example-title" in source
    assert "textContent = sample[0]" in source
    assert "textContent = sample[1]" in source
    assert "textContent = sample[2]" in source
    assert "Aucun message n'est envoyé au serveur" in source
    assert 'channelOptions(route.channel_id ||' in source


def test_responsive_styles_and_reduced_motion_are_bundled():
    source = CSS.read_text(encoding="utf-8")
    html = unified.INDEX_HTML
    assert ".log-center-layout" in source
    assert ".log-route-card" in source
    assert ".log-discord-sample" in source
    assert "@media(max-width:680px)" in source
    assert "@media(prefers-reduced-motion:reduce)" in source
    assert ".log-discord-sample" in html


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js absent")
def test_logs_dashboard_javascript_parses_as_javascript():
    result = subprocess.run(
        ["node", "--check", str(JS)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
