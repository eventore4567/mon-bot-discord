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
    assert "Les droits viennent des permissions Discord" in source


def test_warn_auto_ban_is_configurable_from_setup():
    source = V76.read_text(encoding="utf-8")

    # 11/11/2026 : le titre « Ban automatique » répétait la ligne d'état juste
    # au-dessus ; le menu porte déjà « Choisir le seuil d'avertissements ».
    assert "### Ban automatique" not in source
    assert "Choisir le seuil d'avertissements" in source
    assert "warn_ban_threshold" in source
    assert "2 avertissements" in source
    assert "3 avertissements" in source
    assert "5 avertissements" in source


def test_sanction_dm_configuration_is_available_from_setup():
    source = V76.read_text(encoding="utf-8")

    # Le pavé « MP de sanction » tient en une ligne discrète au-dessus du menu,
    # et les trois boutons sont nommés par ce qu'ils font.
    assert "### MP de sanction" not in source
    assert "MP envoyé au membre sanctionné" in source
    assert "sanction_dm_templates" in source
    assert "Texte par défaut" in source
    assert "✏️ Personnaliser" in source
    assert "🔇 Ne pas envoyer" in source
    assert "{membre}" in source
    assert "{serveur}" in source
    assert "{raison}" in source


def test_v76_is_loaded_after_v75_security_patch():
    source = V75.read_text(encoding="utf-8")

    install_security = source.index("cls._build_security = build_security_page")
    install_v76 = source.index("moderation_v76.install(bot)")
    assert install_security < install_v76


def test_la_page_moderation_suit_la_presentation_de_la_securite():
    """11/11/2026 : « c'est moche ». Même bannière et même sobriété que Sécurité."""
    source = V76.read_text(encoding="utf-8")

    assert "securite_simple.conteneur(" in source, "la bande de bannière manquait"
    assert 'icons.titre("mod", "Modération")' in source
    # Plus de bouton d'état figé : le bouton Activer/Désactiver dit déjà l'état.
    assert 'label="Activée" if enabled else "Désactivée"' not in source
    assert "### État actuel" not in source
    # Les quatre actions tiennent sur une seule rangée.
    assert "ActionRow(use_default, customize, disable_dm, toggle)" in source
