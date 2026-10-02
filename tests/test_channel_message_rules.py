from types import SimpleNamespace

from cogs import channel_message_rules


def _attachment(filename, content_type=None):
    return SimpleNamespace(filename=filename, content_type=content_type)


def _message(content="", attachments=()):
    return SimpleNamespace(content=content, attachments=list(attachments))


def _member(*, bot=False, administrator=False, manage_guild=False, manage_messages=False):
    perms = SimpleNamespace(
        administrator=administrator,
        manage_guild=manage_guild,
        manage_messages=manage_messages,
    )
    return SimpleNamespace(bot=bot, guild_permissions=perms)


def test_images_only_accepts_only_real_images_without_text():
    assert channel_message_rules.message_is_images_only(
        _message("", [_attachment("screen.png", "image/png")])
    )
    assert channel_message_rules.message_is_images_only(
        _message("", [_attachment("a.jpg"), _attachment("b.webp", "image/webp")])
    )


def test_images_only_rejects_text_even_when_an_image_is_attached():
    assert not channel_message_rules.message_is_images_only(
        _message("voici mon image", [_attachment("screen.png", "image/png")])
    )


def test_images_only_rejects_non_image_files_and_empty_messages():
    assert not channel_message_rules.message_is_images_only(
        _message("", [_attachment("document.pdf", "application/pdf")])
    )
    assert not channel_message_rules.message_is_images_only(_message("", []))


def test_channel_rules_bypass_bots_and_staff_only():
    assert channel_message_rules.member_bypasses(_member(bot=True))
    assert channel_message_rules.member_bypasses(_member(administrator=True))
    assert channel_message_rules.member_bypasses(_member(manage_guild=True))
    assert channel_message_rules.member_bypasses(_member(manage_messages=True))
    assert not channel_message_rules.member_bypasses(_member())


def test_setup_and_dashboard_expose_reactions_and_channel_rules():
    setup = open("cogs/setup_v2_ui.py", encoding="utf-8").read()
    dashboard = open("web/dashboard_ui/js/39_automation.js", encoding="utf-8").read()
    api = open("web/dashboard_api_channel_rules.py", encoding="utf-8").read()
    runtime = open("cogs/setup_v2_runtime.py", encoding="utf-8").read()

    assert 'setup_ui.CATEGORIES["automation"]' in setup
    assert 'label="Réactions automatiques"' in setup
    assert 'label="Règles de salons"' in setup
    assert 'sentrix_dashboard_auto_reaction' in setup
    assert "ChannelRuleSetupView" in setup

    assert "['channel-rules', 'Règles de salons']" in dashboard
    assert "/automation/channel-rules" in dashboard
    assert "Images uniquement" in dashboard
    assert "Messages interdits" in dashboard

    assert '"/api/guilds/{guild_id}/automation/channel-rules"' in api
    assert "channel_message_rules.install(bot)" in runtime


def test_configuration_snapshots_include_new_automation_tables():
    source = open("database/db.py", encoding="utf-8").read()
    assert '"sentrix_dashboard_auto_reaction"' in source
    assert '"sentrix_channel_message_rules"' in source
