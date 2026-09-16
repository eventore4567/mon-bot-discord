from sentrix_setup_deep_v116 import (
    AUTOMOD_FIELDS,
    BRIDGE_TARGETS,
    CONFIG_TARGETS,
    MODULES,
    MODULE_BY_KEY,
    PAGE_V116_DETAIL,
    PAGE_V116_MODULES,
    _persisted_page,
)


REQUIRED_MODULES = {
    "security",
    "moderation",
    "members",
    "logs",
    "levels",
    "economy",
    "tickets",
    "roles",
    "notifications",
    "ai",
    "suggestions",
    "profile",
    "smart",
}


def test_v116_has_all_required_configuration_modules():
    assert REQUIRED_MODULES <= set(MODULE_BY_KEY)
    assert len(MODULES) == len(MODULE_BY_KEY)


def test_every_module_has_real_nested_settings():
    for module in MODULES:
        assert module.label.strip()
        assert module.description.strip()
        assert len(module.details) >= 3
        keys = [item.key for item in module.details]
        assert len(keys) == len(set(keys)), module.key
        for detail in module.details:
            assert detail.label.strip()
            assert detail.description.strip()
            assert detail.target.strip()


def test_security_core_is_individually_configurable():
    security = MODULE_BY_KEY["security"]
    targets = {item.target for item in security.details}
    for field in ("antiraid", "antispam", "antilink", "antiinvite", "antiscam", "antinuke"):
        assert f"automod:{field}" in targets


def test_automod_targets_only_reference_known_runtime_fields():
    for module in MODULES:
        for detail in module.details:
            if detail.target.startswith("automod:"):
                assert detail.target.split(":", 1)[1] in AUTOMOD_FIELDS


def test_config_targets_are_known_setup_fields_only():
    referenced = {
        detail.target.split(":", 1)[1]
        for module in MODULES
        for detail in module.details
        if detail.target.startswith("config:")
    }
    assert referenced <= CONFIG_TARGETS
    assert {"mod_role", "welcome_channel", "autorole", "verify_role", "log_channel"} <= referenced


def test_bridge_targets_reference_only_known_existing_panels():
    for module in MODULES:
        for detail in module.details:
            if not detail.target.startswith("bridge:"):
                continue
            bridge = detail.target.split(":", 2)[1]
            assert bridge in BRIDGE_TARGETS


def test_v116_target_protocol_is_explicit_and_non_destructive():
    allowed = ("automod:", "config:", "page:", "action:", "hint:", "bridge:", "native:")
    for module in MODULES:
        for detail in module.details:
            assert detail.target.startswith(allowed), detail.target
            lowered = detail.target.casefold()
            assert "delete" not in lowered
            assert "wipe" not in lowered
            assert "remove" not in lowered


def test_v116_uses_legacy_modules_page_as_restart_safe_entrypoint():
    # Le centre V116 remplace la page Modules existante plutôt que d'inventer une page
    # persistée hors de la plage connue par cogs.configuration.
    assert PAGE_V116_MODULES >= 0
    assert PAGE_V116_DETAIL >= 100
    assert PAGE_V116_MODULES != PAGE_V116_DETAIL
    assert _persisted_page(PAGE_V116_DETAIL) == PAGE_V116_MODULES
    assert _persisted_page(PAGE_V116_MODULES) == PAGE_V116_MODULES
    assert _persisted_page(-1) == -1


def test_labels_stay_compact_for_discord_components():
    for module in MODULES:
        assert len(module.label) <= 30
        assert len(module.description) <= 100
        for detail in module.details:
            assert len(detail.label) <= 40
            assert len(detail.description) <= 100


def test_hierarchy_is_deep_without_becoming_a_flat_button_wall():
    assert len(MODULES) <= 25
    assert max(len(module.details) for module in MODULES) <= 25
    assert sum(len(module.details) for module in MODULES) >= 60


def test_core_modules_open_real_existing_configuration_panels():
    levels = {item.target for item in MODULE_BY_KEY["levels"].details}
    tickets = {item.target for item in MODULE_BY_KEY["tickets"].details}
    ai = {item.target for item in MODULE_BY_KEY["ai"].details}

    assert any(target.startswith("bridge:levels:") for target in levels)
    assert tickets == {"bridge:tickets"}
    assert ai == {"bridge:ai"}


def test_welcome_and_xp_multiplier_have_native_setup_editors():
    members = {item.target for item in MODULE_BY_KEY["members"].details}
    levels = {item.target for item in MODULE_BY_KEY["levels"].details}
    assert "native:welcome_message" in members
    assert "native:xp_multiplier" in levels
