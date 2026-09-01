from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_setup_experience_routes_to_v20_and_registers_finalizer():
    text = source("cogs/setup_experience_v2.py")
    assert "control_center_v20.setup(bot)" in text
    assert 'finalizer = "cogs.control_center_finalizer_v20"' in text
    assert "bot_main.EXTENSIONS.append(finalizer)" in text


def test_v20_has_exact_states_and_requested_categories_without_manager_page():
    text = source("utils/control_center_v20_meta.py")
    for state in ("ACTIF", "INACTIF", "NON CONFIGURÉ", "ERREUR DE CONFIGURATION"):
        assert state in text
    for key in (
        '"moderation"', '"security"', '"logs"', '"tickets"', '"welcome"',
        '"roles"', '"levels_economy"', '"notifications"', '"ai"',
    ):
        assert key in text
    setup_block = text.split("SETUP_CATEGORIES", 1)[1].split("HELP_CATEGORY_ORDER", 1)[0]
    assert '"managers"' not in setup_block
    assert "Gestionnaire du bot" not in setup_block


def test_setup_navigation_edits_one_message_and_has_home_back_refresh():
    text = source("cogs/control_center_setup_v20.py")
    assert 'placeholder="Choisir une catégorie"' in text
    assert 'label="Accueil"' in text
    assert 'label="Retour"' in text
    assert 'label="Actualiser"' in text
    assert "interaction.response.edit_message" in text
    assert "_category_embed" in text
    assert "_home_embed" in text


def test_setup_uses_real_existing_editors_and_services():
    text = source("cogs/control_center_setup_v20.py")
    components = source("cogs/control_center_setup_components_v20.py")
    assert "log_service.set_log_channel" in text
    assert "log_service.set_log_enabled" in text
    assert "TicketSetupHubView" in text
    assert "AiSetupView" in text
    assert "WelcomeTextModal" in text
    assert "SecurityToggleView" in text
    assert "discord.ui.RoleSelect" in components
    assert "discord.ui.ChannelSelect" in components


def test_setup_reads_existing_configuration_and_reports_broken_resources():
    text = source("utils/control_center_v20_state.py")
    assert "get_guild_config(guild.id)" in text
    assert "get_all_log_settings" in text
    assert "ticket_panels_v2" in text
    assert "ticket_types" in text
    assert "social_notifications" in text
    assert "guild.get_channel" in text
    assert "guild.get_role" in text
    assert "validate_channel" in text
    assert "STATE_ERROR" in text
    assert "missing_permissions" in text
    assert '"MANQUANT"' in text or "MANQUANT" in text


def test_completion_treats_intentionally_disabled_module_as_complete():
    meta = source("utils/control_center_v20_meta.py")
    state = source("utils/control_center_v20_state.py")
    assert "return self.state in {STATE_ACTIVE, STATE_INACTIVE}" in meta
    assert "completed = sum(1 for snapshot in snapshots.values() if snapshot.complete)" in state
    assert "percent = round(completed / max(1, len(snapshots)) * 100)" in state


def test_help_lists_all_commands_and_supports_direct_search():
    meta = source("utils/control_center_v20_meta.py")
    facade = source("cogs/control_center_v20.py")
    assert "for command in bot.walk_commands()" in meta
    assert "command.hidden" in meta
    assert "can_run" not in meta
    assert "guild_permissions" not in meta.split("def _all_help_commands", 1)[1].split("def _slash_map", 1)[0]
    assert "_search_help" in facade
    assert "_help_detail_embed" in facade
    assert "Permission nécessaire" in source("utils/control_center_v20_state.py")
    assert "Commande slash" in source("utils/control_center_v20_state.py")


def test_prefix_and_slash_share_the_same_hybrid_implementation():
    text = source("cogs/control_center_v20.py")
    assert '@commands.hybrid_command(\n        name="setup"' in text
    assert '@commands.hybrid_command(\n        name="help"' in text
    assert text.count('name="setup"') >= 1
    assert text.count('name="help"') >= 1
    assert "_remove_command(bot, name)" in text


def test_global_manager_configuration_is_owner_only_and_hidden_from_setup():
    text = source("cogs/control_center_v20.py")
    for command in ("sentrix-manager-list", "sentrix-manager-add", "sentrix-manager-remove"):
        assert command in text
    assert text.count("@checks.is_bot_owner()") >= 3
    assert 'step.get("key") != "managers"' in text
    access = source("utils/control_center_v20_access.py")
    assert "global_bot_managers" in access
    assert "is_bot_manager" not in access


def test_finalizer_prevents_legacy_help_from_replacing_v20():
    text = source("cogs/control_center_finalizer_v20.py")
    assert "plain_text_all_extension._ensure_official_help_on_ready = keep_v20_help" in text
    assert 'bot.get_cog("SentriXControlCenterV20")' in text
    assert 'await bot.remove_cog("SentriXControlCenterV20")' in text
    assert "await control_center_v20.setup(bot)" in text
