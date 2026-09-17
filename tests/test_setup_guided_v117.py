from pathlib import Path

import sentrix_setup_guided_v117 as v117
import sentrix_setup_v116 as v116


def test_v117_keeps_all_primary_modules_available():
    for key in ("security", "moderation", "members", "logs", "levels", "economy", "tickets", "notifications", "ai", "suggestions"):
        assert key in v117.HOME_MODULE_KEYS
        assert key in v116.MODULE_BY_KEY


def test_v117_home_hides_redundant_top_level_modules():
    assert "roles" not in v117.HOME_MODULE_KEYS
    assert "verification" not in v117.HOME_MODULE_KEYS
    assert "profile" not in v117.HOME_MODULE_KEYS


def test_v117_removes_intermediate_and_external_command_language():
    source = Path("sentrix_setup_guided_v117.py").read_text(encoding="utf-8")
    assert "Ouvrir ce réglage" not in source
    assert "choisir un réglage" not in source.lower()
    assert "assistant dédié" not in source.lower()
    assert "lance **`+" not in source.lower()
    assert "hint:+" not in source
    assert "Que veux-tu configurer ?" in source
    assert "Étape **" in source
    assert 'label="Précédent"' in source
    assert 'label="Suivant"' in source
    assert 'label="Accueil"' in source
    assert 'label="Terminer"' in source
    assert "**Résumé**" in source


def test_v117_visible_modules_use_guided_configuration_steps():
    for key in v117.HOME_MODULE_KEYS:
        module = v116.MODULE_BY_KEY[key]
        sections = v117._sections_for(module)
        assert sections
        assert len(sections) <= 25
        assert all(not section.action.startswith("hint:") for section in sections)


def test_v117_replaces_non_configuration_actions_with_real_settings():
    moderation = v117.GUIDED_SECTIONS["moderation"]
    assert {s.action for s in moderation} == {"number:warn_ban_threshold", "config:warn_role"}

    members = v117.GUIDED_SECTIONS["members"]
    member_actions = {s.action for s in members}
    assert "config:welcome_channel" in member_actions
    assert "text:welcome_message" in member_actions
    assert "config:goodbye_channel" in member_actions
    assert "text:goodbye_message" in member_actions
    assert "config:autorole" in member_actions
    assert "config:verify_role" in member_actions

    economy = v117.GUIDED_SECTIONS["economy"]
    assert all(section.action == "levels-config" for section in economy)


def test_v117_complex_modules_open_inside_setup():
    assert v117.GUIDED_SECTIONS["tickets"][0].action == "internal:ticketsetup"
    assert v117.GUIDED_SECTIONS["notifications"][0].action == "internal:notifications"
    assert v117.GUIDED_SECTIONS["ai"][0].action == "internal:aisetup"

    source = Path("sentrix_setup_guided_v117.py").read_text(encoding="utf-8")
    assert "NotificationSetupView" in source
    assert "commands.Context.from_interaction" in source
    assert "ctx.invoke(command)" in source


def test_v117_uses_native_discord_pickers_and_modals():
    source = Path("sentrix_setup_guided_v117.py").read_text(encoding="utf-8")
    assert "discord.ui.RoleSelect" in source
    assert "discord.ui.ChannelSelect" in source
    assert "TextSettingModal" in source
    assert "NumberSettingModal" in source
    assert "set_guild_config" in source


def test_v117_notifications_are_configured_without_notifs_command_redirect():
    source = Path("sentrix_setup_guided_v117.py").read_text(encoding="utf-8")
    assert "social_notifications" in source
    assert "_extract_latest" in source
    assert "Source & texte" in source
    assert "Salon de notification" in source
    assert "Rôle à ping" in source
    assert "+notifs-list" not in source
    assert "+notifs-ping" not in source


def test_v117_is_installed_after_v116_before_setup_authority():
    source = Path("sentrix_v103_setup_fix.py").read_text(encoding="utf-8")
    prepare = source[source.index("async def prepare_bot_v103"):]
    assert prepare.index("install_setup_v116(bot)") < prepare.index("install_setup_v117(bot)")
    assert prepare.index("install_setup_v117(bot)") < prepare.index("_replace_setup_slash(bot)")


def test_v117_does_not_reintroduce_visual_bars_or_technical_status_blocks():
    source = Path("sentrix_setup_guided_v117.py").read_text(encoding="utf-8")
    assert "█" not in source
    assert "░" not in source
    assert "**État actuel**" not in source
    assert "Configuration rapide" not in source
