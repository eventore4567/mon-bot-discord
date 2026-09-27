from pathlib import Path

import config
from web import public_verification_v120 as web_verify


WEB_SOURCE = Path("web/public_verification_v120.py").read_text(encoding="utf-8")
DASHBOARD_SOURCE = Path("web/dashboard.py").read_text(encoding="utf-8")
HONEYPOT_SOURCE = Path("cogs/honeypot_verification_v48.py").read_text(encoding="utf-8")
SETUP_SOURCE = Path("cogs/setup_v118_integrations.py").read_text(encoding="utf-8")
MODERATION_SOURCE = Path("cogs/moderation.py").read_text(encoding="utf-8")


def test_web_verification_files_compile():
    compile(WEB_SOURCE, "web/public_verification_v120.py", "exec")
    compile(HONEYPOT_SOURCE, "cogs/honeypot_verification_v48.py", "exec")
    compile(SETUP_SOURCE, "cogs/setup_v118_integrations.py", "exec")


def test_challenge_is_signed_and_bound_to_user_and_guild(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_CLIENT_SECRET", "x" * 64)
    token = web_verify.issue_challenge(123, 456, "ABC234", "17")
    assert web_verify.validate_challenge(
        token,
        guild_id=123,
        user_id=456,
        captcha="abc234",
        math_answer="17",
    )
    assert not web_verify.validate_challenge(
        token,
        guild_id=123,
        user_id=999,
        captcha="ABC234",
        math_answer="17",
    )
    assert not web_verify.validate_challenge(
        token,
        guild_id=123,
        user_id=456,
        captcha="WRONG1",
        math_answer="17",
    )


def test_verification_session_is_signed_and_scoped(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_CLIENT_SECRET", "y" * 64)
    token = web_verify.make_session_token(321, 654)
    payload = web_verify.parse_session_token(token, guild_id=321)
    assert payload
    assert payload["gid"] == 321
    assert payload["uid"] == 654
    assert web_verify.parse_session_token(token, guild_id=999) is None


def test_dashboard_oauth_routes_back_to_verification():
    assert "verify_guild" in DASHBOARD_SOURCE
    assert "make_verify_session_token" in DASHBOARD_SOURCE
    assert 'web.HTTPFound(f"/verify/{verify_guild_id}")' in DASHBOARD_SOURCE
    assert "register_public_verification" in DASHBOARD_SOURCE


def test_web_page_has_loading_success_close_and_discord_redirect():
    assert "spinner" in WEB_SOURCE
    assert "showSuccess" in WEB_SOURCE
    assert "window.close()" in WEB_SOURCE
    assert "discord://-/channels/" in WEB_SOURCE
    assert "https://discord.com/channels/" in WEB_SOURCE
    assert "captcha_image" in WEB_SOURCE


def test_active_panel_is_web_link_and_startup_never_recreates_missing_channels():
    assert "await _web_panel(self.bot, guild)" in HONEYPOT_SOURCE
    assert "refresh_existing_panels" in HONEYPOT_SOURCE
    repair = HONEYPOT_SOURCE[HONEYPOT_SOURCE.index("async def _repair_enabled_systems"):]
    repair = repair[:repair.index("async def install")]
    assert "create_text_channel(" not in repair
    assert "create_category(" not in repair
    assert "create_or_refresh_system(" not in repair
    assert "aucune recréation" in repair


def test_one_time_cleanup_only_targets_old_duplicate_verification_channels():
    assert "_cleanup_spam_verification_channels" in HONEYPOT_SOURCE
    assert 'channel.name.casefold() not in {"verification", "stay-muted"}' in HONEYPOT_SOURCE
    assert "_channel_is_bot_only" in HONEYPOT_SOURCE
    assert "keep_ids" in HONEYPOT_SOURCE
    assert "_WEB_CLEANUP_MIGRATION" in HONEYPOT_SOURCE


def test_existing_active_setup_updates_panels_without_creating_structure():
    assert "refresh_existing_panels(interaction.guild)" in SETUP_SOURCE
    assert "Aucun salon ni catégorie n'a été créé." in SETUP_SOURCE
    assert "create_or_refresh_system" in SETUP_SOURCE


def test_clear_and_clearwarnings_no_longer_double_confirm():
    clear_start = MODERATION_SOURCE.index("async def clear(self")
    clear_chunk = MODERATION_SOURCE[clear_start:clear_start + 2200]
    assert "double_confirm_destructive" not in clear_chunk

    warnings_start = MODERATION_SOURCE.index("async def clearwarnings")
    warnings_chunk = MODERATION_SOURCE[warnings_start:warnings_start + 1200]
    assert "double_confirm_destructive" not in warnings_chunk


def test_success_dm_matches_requested_green_verification_style():
    assert 'title=f"Verification successful on {guild.name}"' in WEB_SOURCE
    assert "discord.Colour.green()" in WEB_SOURCE
    assert 'label="Open server"' in WEB_SOURCE
