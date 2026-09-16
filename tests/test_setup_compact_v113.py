from sentrix_setup_compact_v113 import (
    AUTO_SCOPES,
    CHANNEL_TARGETS,
    SMART_TEMPLATES,
    _clean_name,
    _plan_signature,
    _score_colour,
    _template_targets,
)


def test_clean_name_is_accent_and_case_insensitive():
    assert _clean_name("  MODÉRATEUR  ") == "moderateur"
    assert _clean_name("BiénVénue") == "bienvenue"


def test_score_colour_uses_three_clear_states():
    assert _score_colour(-50) == 0xF23F43
    assert _score_colour(54) == 0xF23F43
    assert _score_colour(55) == 0xF0B232
    assert _score_colour(79) == 0xF0B232
    assert _score_colour(80) == 0x23A559
    assert _score_colour(500) == 0x23A559


def test_all_templates_only_reference_supported_channels():
    supported = set(CHANNEL_TARGETS)
    assert SMART_TEMPLATES
    for key, template in SMART_TEMPLATES.items():
        assert template["label"]
        assert template["security"] in {"faible", "moyen", "eleve"}
        assert set(_template_targets(key)) <= supported


def test_private_template_does_not_create_public_structure():
    assert _template_targets("private") == ()


def test_unknown_template_falls_back_to_balanced():
    assert _template_targets("does-not-exist") == _template_targets("balanced")


def test_plan_signature_changes_when_preview_relevant_data_changes():
    base = [{
        "kind": "create_channel",
        "scope": "channels",
        "key": "welcome_channel",
        "name": "bienvenue",
        "automatic": True,
    }]
    changed = [{**base[0], "name": "welcome"}]
    assert _plan_signature(base) != _plan_signature(changed)
    assert _plan_signature(base) == _plan_signature([dict(base[0])])


def test_smart_setup_scopes_are_explicit_and_non_destructive():
    assert set(AUTO_SCOPES) == {"security", "logs", "roles", "channels", "community"}
    assert all("delete" not in key and "remove" not in key for key in AUTO_SCOPES)
