import inspect

import discord

from sentrix_setup_compact_v113 import (
    AUTO_SCOPES,
    CHANNEL_TARGETS,
    SMART_TEMPLATES,
    _clean_name,
    _plan_signature,
    _score_colour,
    _template_targets,
)
from sentrix_setup_polish_v114 import (
    _auto_embed,
    _compact_component_rows,
    _configuration_embed,
    _home_embed,
    _is_setup_embed,
    _modules_embed,
    _progress_bar,
    _security_embed,
    _status_label,
    _summary_embed,
    _upgrade_only_values,
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


def test_progress_bar_is_bounded_and_fixed_width_for_backward_compatibility():
    assert _progress_bar(-20, 10) == "░" * 10
    assert _progress_bar(100, 10) == "█" * 10
    assert len(_progress_bar(55, 10)) == 10
    assert len(_progress_bar(50, 2)) == 4
    assert len(_progress_bar(50, 99)) == 20


def test_status_label_has_clear_product_states():
    assert _status_label(0) == "PRIORITAIRE"
    assert _status_label(50) == "À RENFORCER"
    assert _status_label(75) == "BON"
    assert _status_label(90) == "EXCELLENT"


def test_smart_setup_security_upgrade_never_disables_existing_protection():
    current = {
        "antispam": 1,
        "antilink": 1,
        "antiinvite": 0,
        "antiraid": 0,
        "antiscam": 1,
        "antinuke": 1,
    }
    medium = {
        "antispam": 1,
        "antilink": 0,
        "antiinvite": 1,
        "antiraid": 1,
        "antiscam": 1,
        "antinuke": 1,
    }
    upgrades = _upgrade_only_values(current, medium)
    assert upgrades == {"antiinvite": 1, "antiraid": 1}
    assert "antilink" not in upgrades
    assert all(value == 1 for value in upgrades.values())


def test_security_upgrade_is_idempotent_when_target_is_already_satisfied():
    current = {"antispam": 1, "antiraid": 1, "antiscam": 1}
    target = {"antispam": 1, "antiraid": 1, "antiscam": 1}
    assert _upgrade_only_values(current, target) == {}


def test_primary_setup_renderers_have_no_visual_bars_or_embed_fields():
    renderers = (
        _home_embed,
        _configuration_embed,
        _security_embed,
        _modules_embed,
        _auto_embed,
        _summary_embed,
    )
    for renderer in renderers:
        source = inspect.getsource(renderer)
        assert "_progress_bar(" not in source
        assert ".add_field(" not in source
        assert "█" not in source
        assert "░" not in source


def test_setup_embed_detection_is_scoped_to_setup():
    setup = discord.Embed(title="Configuration")
    setup.set_footer(text="SentriX • Setup • Configuration")
    assert _is_setup_embed(setup) is True

    normal = discord.Embed(title="SentriX • Configuration")
    normal.set_footer(text="SentriX • Configuration")
    assert _is_setup_embed(normal) is False


def test_compact_rows_keep_same_row_buttons_together():
    buttons = [
        discord.ui.Button(label="Configuration", row=0),
        discord.ui.Button(label="Sécurité", row=0),
        discord.ui.Button(label="Modules", row=0),
    ]
    rows = _compact_component_rows(buttons)
    assert len(rows) == 1
    assert len(rows[0].children) == 3


def test_primary_setup_descriptions_are_deliberately_short_by_source_contract():
    for renderer in (_home_embed, _configuration_embed, _security_embed, _modules_embed, _auto_embed, _summary_embed):
        source = inspect.getsource(renderer)
        assert "[:400]" in source or "description=description[:400]" in source
