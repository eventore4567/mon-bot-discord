from __future__ import annotations

import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from web import public_home_v3


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
        'const interactive=$(".card,.step,.security-box,.tour-screen,.ai-card,.terminal")',
        'perspective(1000px) rotateX(',
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
    assert 'href="/privacy"' in page
    assert 'href="/terms"' in page
    assert "https://discord.com/oauth2/authorize?client_id=123&amp;scope=bot" in page


def test_v3_home_never_boots_private_guild_data():
    page = _html()
    assert 'fetch("/api/guilds"' not in page
    assert 'fetch("/api/guilds/' not in page
    assert "csrf" not in page.lower()


def test_v3_is_mobile_and_accessibility_aware():
    page = _html()
    assert "@media(max-width:720px)" in page
    assert "@media(max-width:430px)" in page
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
