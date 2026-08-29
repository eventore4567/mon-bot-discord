from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V76 = ROOT / "cogs" / "setup_moderation_clear_v76.py"
V75 = ROOT / "cogs" / "setup_security_choice_v75.py"


def test_role_builder_is_removed_from_moderation_setup():
    source = V76.read_text(encoding="utf-8")

    assert "Rôle Discord à configurer" not in source
    assert "Choisir les droits de ce rôle" not in source
    assert "Donner ce rôle à un membre" not in source
    assert "Enregistrer les permissions" not in source
    assert "aucun rôle de modération n'est à créer ou à préparer" in source


def test_warn_auto_ban_is_configurable_from_setup():
    source = V76.read_text(encoding="utf-8")

    assert "Bannissement automatique après avertissements" in source
    assert "warn_ban_threshold" in source
    assert "2 avertissements" in source
    assert "3 avertissements" in source
    assert "5 avertissements" in source


def test_sanction_dm_configuration_is_available_from_setup():
    source = V76.read_text(encoding="utf-8")

    assert "Messages privés envoyés lors des sanctions" in source
    assert "sanction_dm_templates" in source
    assert "Texte par défaut" in source
    assert "Personnaliser le MP" in source
    assert "Désactiver le MP" in source
    assert "{membre}" in source
    assert "{serveur}" in source
    assert "{raison}" in source


def test_v76_is_loaded_after_v75_security_patch():
    source = V75.read_text(encoding="utf-8")

    install_security = source.index("cls._build_security = _build_security_v75")
    install_v76 = source.index("moderation_v76.install(bot)")
    assert install_security < install_v76
