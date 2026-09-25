from __future__ import annotations

import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from web import public_support_v1


class _Dashboard:
    @staticmethod
    def _public_url(_request):
        return "https://sentrix.example"


def _html(support_url: str = "https://discord.gg/example") -> str:
    request = SimpleNamespace(app={"bot": object()})
    return public_support_v1.render(request, _Dashboard, support_url)


def test_support_v1_is_interactive_and_premium():
    page = _html()
    for marker in (
        'id="cursorGlow"',
        'class="support-visual"',
        'class="support-console"',
        'class="support-card reveal"',
        'class="diagnose reveal"',
        'data-key="commands"',
        'data-key="dashboard"',
        'data-key="permissions"',
        'data-key="security"',
        'id="diagContent"',
    ):
        assert marker in page


def test_support_v1_moves_with_pointer_and_respects_reduced_motion():
    page = _html()
    assert 'addEventListener("pointermove"' in page
    assert 'perspective(900px) rotateX(' in page
    assert 'perspective(1200px) rotateX(' in page
    assert "IntersectionObserver" in page
    assert "@media(prefers-reduced-motion:reduce)" in page


def test_support_v1_uses_real_support_url_when_configured():
    page = _html("https://discord.gg/sentrix")
    assert "https://discord.gg/sentrix" in page
    assert "Rejoindre le serveur support" in page


def test_support_v1_has_safe_fallback_without_support_url():
    page = _html("")
    assert 'href="/app">Ouvrir le dashboard</a>' in page
    assert "Le lien public du serveur support n’est pas encore configuré." in page


def test_support_v1_does_not_request_private_dashboard_data():
    page = _html()
    assert 'fetch("/api/me"' not in page
    assert 'fetch("/api/guilds"' not in page
    assert "csrf" not in page.lower()


def test_support_v1_javascript_syntax_is_valid(tmp_path: Path):
    node = subprocess.run(["node", "--version"], capture_output=True, text=True)
    if node.returncode != 0:
        pytest.skip("node indisponible")
    page = _html()
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    assert len(scripts) == 1
    target = tmp_path / "support-v1.js"
    target.write_text(scripts[0], encoding="utf-8")
    result = subprocess.run(["node", "--check", str(target)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
