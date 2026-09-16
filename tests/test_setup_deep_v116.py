from sentrix_setup_deep_v116 import (
    AUTOMOD_FIELDS,
    CONFIG_TARGETS,
    MODULES,
    MODULE_BY_KEY,
    PAGE_V116_DETAIL,
    PAGE_V116_MODULES,
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


def test_v116_target_protocol_is_explicit_and_non_destructive():
    allowed = ("automod:", "config:", "page:", "action:", "hint:")
    for module in MODULES:
        for detail in module.details:
            assert detail.target.startswith(allowed), detail.target
            lowered = detail.target.casefold()
            assert "delete" not in lowered
            assert "wipe" not in lowered
            assert "remove" not in lowered


def test_pages_do_not_overlap_legacy_setup_pages():
    assert PAGE_V116_MODULES >= 100
    assert PAGE_V116_DETAIL >= 100
    assert PAGE_V116_MODULES != PAGE_V116_DETAIL


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
