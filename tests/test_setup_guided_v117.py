from pathlib import Path

import sentrix_setup_guided_v117 as v117
import sentrix_setup_v116 as v116


def test_v117_keeps_all_v116_modules_available():
    assert len(v116.MODULES) >= 10
    assert "verification" in v116.MODULE_BY_KEY
    assert "security" in v116.MODULE_BY_KEY
    assert "logs" in v116.MODULE_BY_KEY
    assert "tickets" in v116.MODULE_BY_KEY


def test_v117_removes_intermediate_section_picker_language():
    source = Path("sentrix_setup_guided_v117.py").read_text(encoding="utf-8")
    assert "Ouvrir ce réglage" not in source
    assert "choisir un réglage" not in source.lower()
    assert "Que veux-tu configurer ?" in source
    assert "Étape **" in source
    assert 'label="Précédent"' in source
    assert 'label="Suivant"' in source
    assert 'label="Accueil"' in source


def test_v117_uses_clear_action_labels():
    verification = v116.MODULE_BY_KEY["verification"]
    role = next(section for section in verification.sections if section.key == "role")
    assert v117._action_label(role) == "Choisir le rôle"

    members = v116.MODULE_BY_KEY["members"]
    welcome = next(section for section in members.sections if section.key == "welcome")
    assert v117._action_label(welcome) == "Choisir le salon"

    security = v116.MODULE_BY_KEY["security"]
    protections = next(section for section in security.sections if section.key == "automod")
    assert v117._action_label(protections) == "Configurer la protection"


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
