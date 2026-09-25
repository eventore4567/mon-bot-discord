from __future__ import annotations

import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from web import public_home_v2


class _Dashboard:
    @staticmethod
    def _public_url(_request):
        return "https://sentrix.example"

    @staticmethod
    def _invite_url(_bot):
        return "https://discord.com/oauth2/authorize?client_id=123&scope=bot"


def _html() -> str:
    return public_home_v2.render(SimpleNamespace(app={"bot": object()}), _Dashboard)


def test_v2_is_visually_rich_and_has_all_major_sections():
    page = _html()
    for marker in (
        'class="hero-shell"',
        'class="hero-visual"',
        'class="console"',
        'class="module-marquee"',
        'class="bento"',
        'id="security"',
        'id="dashboard"',
        'id="automation"',
        'id="ai"',
        'id="faq"',
        'class="final reveal"',
    ):
        assert marker in page


def test_v2_has_visible_motion_not_only_static_hover_effects():
    page = _html()
    for marker in (
        "@keyframes heroUp",
        "@keyframes consoleFloat",
        "@keyframes marquee",
        "@keyframes radarSpin",
        "@keyframes drawLine",
        "@keyframes bubbleIn",
        "IntersectionObserver",
        'addEventListener("pointermove"',
        'id="progress"',
    ):
        assert marker in page
    assert "@media(prefers-reduced-motion:reduce)" in page


def test_v2_public_data_is_real_and_not_fake_marketing_numbers():
    page = _html()
    assert 'fetch("/api/public"' in page
    assert 'id="publicGuilds">—</strong>' in page
    assert 'id="publicMembers">—</strong>' in page
    assert "99.99%" not in page
    assert "100 000 serveurs" not in page
    assert "millions de membres" not in page.lower()


def test_v2_keeps_dashboard_auth_and_public_routes():
    page = _html()
    assert 'href="/app" data-dashboard-entry' in page
    assert 'fetch("/api/me"' in page
    assert 'href="/support"' in page
    assert 'href="/commands"' in page
    assert 'href="/privacy"' in page
    assert 'href="/terms"' in page
    assert "https://discord.com/oauth2/authorize?client_id=123&amp;scope=bot" in page


def test_v2_does_not_boot_private_dashboard_data_on_home():
    page = _html()
    assert 'fetch("/api/guilds"' not in page
    assert 'fetch("/api/guilds/' not in page
    assert "csrf" not in page.lower()


def test_v2_is_mobile_and_accessibility_aware():
    page = _html()
    assert "@media(max-width:720px)" in page
    assert "@media(max-width:430px)" in page
    assert 'class="skip" href="#main"' in page
    assert 'aria-label="Navigation principale"' in page
    assert 'aria-expanded="false"' in page


def test_v2_javascript_syntax_is_valid(tmp_path: Path):
    node = subprocess.run(["node", "--version"], capture_output=True, text=True)
    if node.returncode != 0:
        pytest.skip("node indisponible")
    page = _html()
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    assert len(scripts) == 1
    target = tmp_path / "public-home-v2.js"
    target.write_text(scripts[0], encoding="utf-8")
    result = subprocess.run(["node", "--check", str(target)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
