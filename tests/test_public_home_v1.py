from __future__ import annotations

from types import SimpleNamespace

from web import public_home_v1


class _Dashboard:
    @staticmethod
    def _public_url(_request):
        return "https://sentrix.example"

    @staticmethod
    def _invite_url(_bot):
        return "https://discord.com/oauth2/authorize?client_id=123&scope=bot"


def _html() -> str:
    request = SimpleNamespace(app={"bot": object()})
    return public_home_v1.render(request, _Dashboard)


def test_public_home_is_a_real_landing_page_not_the_dashboard_program():
    page = _html()
    assert "<title>SentriX — Modération, sécurité et gestion Discord</title>" in page
    assert 'id="features"' in page
    assert 'id="security"' in page
    assert 'id="dashboard"' in page
    assert 'id="ai"' in page
    assert 'id="faq"' in page
    assert 'id="sentrix-dashboard-unified-v2"' not in page


def test_public_home_keeps_dashboard_and_invite_destinations_real():
    page = _html()
    assert 'href="/app" data-dashboard-entry' in page
    assert "https://discord.com/oauth2/authorize?client_id=123&amp;scope=bot" in page
    assert 'href="/support"' in page
    assert 'href="/privacy"' in page
    assert 'href="/terms"' in page
    assert 'href="/commands"' in page
    assert "__INVITE__" not in page
    assert "__CANONICAL__" not in page


def test_public_home_only_uses_real_public_stats_and_does_not_poll_aggressively():
    page = _html()
    assert 'fetch("/api/public"' in page
    assert 'id="publicGuilds">—</strong>' in page
    assert 'id="publicMembers">—</strong>' in page
    assert 'id="publicLatency">—</strong>' in page
    assert "setInterval(loadPublic" not in page
    assert "100 000 serveurs" not in page
    assert "99.99%" not in page


def test_public_home_is_mobile_accessible_and_respects_reduced_motion():
    page = _html()
    assert 'id="menuBtn"' in page
    assert 'aria-expanded="false"' in page
    assert 'class="skip" href="#main"' in page
    assert "@media(max-width:680px)" in page
    assert "@media(prefers-reduced-motion:reduce)" in page
    assert "IntersectionObserver" in page


def test_public_home_preserves_visible_oauth_failure_feedback():
    page = _html()
    assert 'id="sxAuthNotice"' in page
    assert 'params.get("auth")==="missing"' in page
    assert "notice.hidden=false" in page
    assert "history.replaceState" in page


def test_public_home_has_no_private_dashboard_boot_or_guild_api_fetch():
    page = _html()
    assert 'fetch("/api/guilds"' not in page
    assert 'fetch("/api/guilds/' not in page
    assert 'fetch("/api/me"' in page  # uniquement au clic Dashboard pour choisir /app ou /login
    assert "csrf" not in page.lower()


def test_public_home_canonical_is_current_public_origin():
    page = _html()
    assert '<link rel="canonical" href="https://sentrix.example/">' in page
    assert '<meta property="og:url" content="https://sentrix.example/">' in page
