from cogs import setup_v2_core as core
from cogs import setup_v2_ui as ui


def test_v2_maps_everyday_commands_to_expected_modules():
    assert core._operation_module("mute") == "moderation"
    assert core._operation_module("ban") == "moderation"
    assert core._operation_module("daily") == "economy"
    assert core._operation_module("balance") == "economy"
    assert core._operation_module("level") == "levels"
    assert core._operation_module("ai") == "ai"
    assert core._operation_module("image") == "ai"
    assert core._operation_module("ticket") == "tickets"
    assert core._operation_module("help") is None


def test_v2_currency_replacement_keeps_custom_name_and_symbol():
    settings = {
        "currency_singular": "Crédit",
        "currency_plural": "Crédits",
        "currency_symbol": "¤",
    }
    value = core._replace_currency_text("1 Pièce 🪙 puis 25 Pièces 🪙", settings)
    assert value == "1 Crédit ¤ puis 25 Crédits ¤"


def test_v2_setup_exposes_expected_module_categories():
    assert set(core.MODULES) == {
        "moderation", "security", "logs", "tickets", "welcome", "roles",
        "levels", "economy", "notifications", "ai",
    }
    assert ui.MODULE_BY_CATEGORY["moderation"] == "moderation"
    assert ui.MODULE_BY_CATEGORY["security"] == "security"
    assert ui.MODULE_BY_CATEGORY["notifications"] == "notifications"


def test_whitelist_is_global_not_named_antinuke_only():
    # Le contrat V2 utilise une table centrale de confiance ; la table historique
    # antinuke_whitelist n'est gardée que pour compatibilité/migration.
    source = core.__file__
    assert source
    assert hasattr(core, "add_trusted")
    assert hasattr(core, "remove_trusted")
    assert hasattr(core, "is_trusted")
