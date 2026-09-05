from pathlib import Path

import sentrix_product_update as update


ROOT = Path(__file__).resolve().parents[1]


def test_unknown_command_is_exact_plain_help_message():
    assert update.UNKNOWN_COMMAND_TEXT == "Commande introuvable. Merci de consulter les commandes avec /help."
    assert "Vouliez-vous dire" not in update.UNKNOWN_COMMAND_TEXT


def test_ticket_configuration_is_dashboard_only_but_runtime_commands_are_not_removed():
    expected_config = {
        "ticketsetup",
        "ticketpanel",
        "ticketpanel-toggle",
        "tickettype",
        "ticketform",
        "ticketconfig",
        "ticketlogs",
        "ticketlimit",
        "ticketautoclose",
        "ticket-role",
    }
    assert expected_config <= update.TICKET_CONFIG_COMMANDS
    assert "ticket" not in update.TICKET_CONFIG_COMMANDS
    assert "ticket-reopen" not in update.TICKET_CONFIG_COMMANDS
    assert "tickettranscript" not in update.TICKET_CONFIG_COMMANDS
    assert "ticketstats" not in update.TICKET_CONFIG_COMMANDS


def test_dashboard_routes_are_installed_before_http_start():
    source = (ROOT / "railway_boot.py").read_text(encoding="utf-8")
    install_at = source.index("_install_dashboard_loader_guard_prestart()")
    start_at = source.index("await real_start_dashboard(bot)")
    assert install_at < start_at
    assert "install_dashboard_prestart(dashboard_web)" in source


def test_dashboard_product_layer_contains_required_centres_and_recovery():
    source = (ROOT / "sentrix_product_update.py").read_text(encoding="utf-8")
    assert "embed_dashboard.install(dashboard)" in source
    assert "ticket_center_v35.install(dashboard)" in source
    assert "ticket_buttons_editor_v53.install(dashboard)" in source
    assert "ticket_ping_dashboard.install(dashboard)" in source
    assert 'id="sentrix-product-dashboard-recovery"' in source
    assert 'request("/api/me")' in source
    assert 'request("/api/guilds")' in source
    assert 'Cache-Control' in source and "no-store" in source


def test_rolepanel_builder_exposes_exact_custom_emoji_picker():
    source = (ROOT / "sentrix_product_update.py").read_text(encoding="utf-8")
    assert "Choisir les emojis" in source
    assert "Un emoji par ligne, dans l'ordre des rôles" in source
    assert "custom_emojis" in source
    assert "Chaque rôle doit avoir un emoji différent" in source


def test_regression_shim_applies_product_update_last():
    source = (ROOT / "cogs" / "sentrix_regression_fix.py").read_text(encoding="utf-8")
    assert "await _regression_setup(bot)" in source
    assert "await install_runtime(bot)" in source
    assert source.index("await _regression_setup(bot)") < source.index("await install_runtime(bot)")
