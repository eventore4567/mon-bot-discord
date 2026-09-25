from __future__ import annotations

import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from web import public_support_v2


class _Dashboard:
    @staticmethod
    def _public_url(_request):
        return "https://sentrix.example"


def _html(support_url: str = "https://discord.gg/example") -> str:
    return public_support_v2.render(SimpleNamespace(app={"bot": object()}), _Dashboard, support_url)


def test_support_v2_is_professional_and_intelligent():
    page = _html()
    for marker in (
        'id="smartAssistant"',
        'id="issueType"',
        'id="deviceType"',
        'id="serverContext"',
        'id="errorText"',
        'id="expectedText"',
        'id="actualText"',
        'id="analyzeBtn"',
        'id="reportText"',
        'id="copyReport"',
        "const rules={",
        "Vérifications suggérées",
        "Analyse locale",
    ):
        assert marker in page


def test_support_v2_has_fluid_pointer_and_touch_motion():
    page = _html()
    assert 'requestAnimationFrame(()=>animate(el))' in page
    assert 'pointerType!=="touch"' in page
    assert 'pointerType==="touch"' in page
    assert 'perspective(1050px) rotateX(' in page
    assert 'class="support-card reveal"' in page
    assert 'class="smart-assistant reveal"' in page


def test_support_v2_covers_phone_tablet_laptop_and_large_desktop():
    page = _html()
    for marker in (
        "@media(max-width:1024px)",
        "@media(max-width:768px)",
        "@media(max-width:650px)",
        "@media(max-width:430px)",
        "@media(max-width:360px)",
        "320–430 px",
        "768 px",
        "1024–1440 px",
        "1920 px+",
    ):
        assert marker in page
    assert "@media(prefers-reduced-motion:reduce)" in page


def test_support_v2_report_is_local_and_never_sends_private_data():
    page = _html()
    assert "Rien n’est envoyé automatiquement." in page
    assert "navigator.clipboard.writeText" in page
    assert 'fetch("/api/me"' not in page
    assert 'fetch("/api/guilds"' not in page
    assert "token Discord" in page
    assert "secret OAuth" in page


def test_support_v2_keeps_real_support_link_and_fallback():
    configured = _html("https://discord.gg/sentrix")
    assert "https://discord.gg/sentrix" in configured
    assert "Rejoindre le serveur support" in configured

    fallback = _html("")
    assert 'href="/app">Ouvrir le dashboard</a>' in fallback
    assert "Le lien public du serveur support n’est pas encore configuré." in fallback


def test_support_v2_javascript_syntax_is_valid(tmp_path: Path):
    node = subprocess.run(["node", "--version"], capture_output=True, text=True)
    if node.returncode != 0:
        pytest.skip("node indisponible")
    scripts = re.findall(r"<script>(.*?)</script>", _html(), re.S)
    assert len(scripts) == 1
    target = tmp_path / "support-v2.js"
    target.write_text(scripts[0], encoding="utf-8")
    result = subprocess.run(["node", "--check", str(target)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
