from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V76 = ROOT / "cogs" / "setup_moderation_clear_v76.py"
V75 = ROOT / "cogs" / "setup_security_choice_v75.py"


def test_moderation_setup_explains_the_three_steps_clearly():
    source = V76.read_text(encoding="utf-8")

    assert "Donner des droits de modération à un rôle" in source
    assert "1. Choisir le rôle (ex. Modérateur)" in source
    assert "2. Choisir les droits de ce rôle" in source
    assert "3. Donner ce rôle à un membre (facultatif)" in source
    assert "Enregistrer les permissions" in source


def test_moderation_profiles_are_named_by_user_intent():
    source = V76.read_text(encoding="utf-8")

    assert "Modération légère" in source
    assert "Modération standard" in source
    assert "Modération avancée" in source
    assert "sans Administrateur" in source


def test_sanction_roles_are_explained_as_optional_badges():
    source = V76.read_text(encoding="utf-8")

    assert "ne donnent pas accès aux commandes de modération" in source
    assert "Badge temporaire donné pendant un mute" in source
    assert "Badge donné automatiquement après un warn" in source


def test_v76_is_loaded_after_v75_security_patch():
    source = V75.read_text(encoding="utf-8")

    install_security = source.index("cls._build_security = _build_security_v75")
    install_v76 = source.index("moderation_v76.install(bot)")
    assert install_security < install_v76
