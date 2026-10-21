from pathlib import Path

from sentrix_setup_v116 import MODULES, MODULE_BY_KEY, PAGE_V116_MODULE, module_keys, section_keys


def test_v116_exposes_all_primary_setup_domains():
    expected = {
        "security", "surveillance", "moderation", "verification", "tickets", "staff",
        "welcome_goodbye", "economy", "xp", "games", "music", "events", "ai",
        "automations", "advanced",
    }
    assert set(module_keys()) == expected
    assert expected <= set(MODULE_BY_KEY)
    assert PAGE_V116_MODULE > 100


def test_v116_modules_and_sections_fit_discord_select_limits():
    assert 1 <= len(MODULES) <= 25
    for module in MODULES:
        assert module.label
        assert module.description
        assert 1 <= len(module.sections) <= 25
        assert len(section_keys(module.key)) == len(set(section_keys(module.key)))
        for section in module.sections:
            assert section.label
            assert section.description
            assert len(section.label) <= 100
            assert len(section.description) <= 100


def test_v116_has_real_depth_for_core_modules():
    assert len(section_keys("security")) >= 5
    assert len(section_keys("surveillance")) >= 8
    assert len(section_keys("xp")) >= 5
    assert len(section_keys("welcome_goodbye")) >= 5
    assert len(section_keys("economy")) >= 5


def test_v116_reuses_existing_engines_instead_of_copying_them():
    actions = {section.action for module in MODULES for section in module.sections}
    assert "security" in actions
    assert "logs" in actions
    assert "levels-config" in actions
    assert "verification" in actions
    assert "diagnostic" in actions
    assert any(action.startswith("config:") for action in actions)
    assert any(action.startswith("hint:") for action in actions)


def test_v116_public_categories_show_permissions_and_no_decorative_premium_ui():
    source = Path("sentrix_setup_v116.py").read_text(encoding="utf-8")
    assert "CATEGORY_PERMISSIONS" in source
    assert "Permissions nécessaires" in source
    assert "bouton premium" not in source.casefold()
    assert "badge premium" not in source.casefold()


def test_v116_setup_visual_contract_stays_compact():
    source = Path("sentrix_setup_v116.py").read_text(encoding="utf-8")
    # Les fausses barres qui rendaient V114 illisible ne doivent pas revenir.
    assert "█" not in source
    assert "░" not in source
    # Navigation hiérarchique, pas une forêt de boutons permanents.
    assert "Choisir un module à configurer" in source
    assert "choisir un réglage" in source
    assert "Ouvrir ce réglage" in source


def test_v103_installs_v116_after_existing_prepare_chain():
    source = Path("sentrix_v103_setup_fix.py").read_text(encoding="utf-8")
    assert "result = await current_prepare(bot)" in source
    assert "from sentrix_setup_v116 import install_for_bot as install_setup_v116" in source
    prepare = source[source.index("async def prepare_bot_v103"):]
    assert prepare.index("result = await current_prepare(bot)") < prepare.index("install_setup_v116(bot)")
    assert prepare.index("install_setup_v116(bot)") < prepare.index("_replace_setup_slash(bot)")
    # Le contrat d'autorité V105/V114 reste stable pour ne pas casser le slash guard.
    assert '_sentrix_setup_authority = "configuration-v114"' in source
