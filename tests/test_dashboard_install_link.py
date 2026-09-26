from __future__ import annotations

from types import SimpleNamespace

import web.dashboard as dashboard


EXPECTED = "https://discord.com/oauth2/authorize?client_id=1532010415951839252"


def test_generic_add_sentrix_uses_exact_requested_install_link():
    assert dashboard.BOT_INSTALL_URL == EXPECTED
    assert dashboard._invite_url(SimpleNamespace(user=None)) == EXPECTED


def test_guild_add_sentrix_uses_the_same_canonical_install_link():
    assert dashboard._invite_url(SimpleNamespace(user=None), guild_id=123456789) == EXPECTED


def test_dashboard_login_oauth_remains_separate_from_bot_install_link(monkeypatch):
    monkeypatch.setattr(dashboard.config, "DISCORD_CLIENT_ID", "999999999999999999")
    bot = SimpleNamespace(user=SimpleNamespace(id=111))
    assert dashboard._client_id(bot) == "999999999999999999"
    assert dashboard._invite_url(bot) == EXPECTED
