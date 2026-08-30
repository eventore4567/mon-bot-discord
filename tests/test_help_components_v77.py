import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELP_V77 = ROOT / "cogs" / "help_components_v77.py"
SECURITY_V75 = ROOT / "cogs" / "setup_security_choice_v75.py"


def test_help_v77_is_valid_python_and_uses_components_v2():
    source = HELP_V77.read_text(encoding="utf-8")
    ast.parse(source)

    assert "discord.ui.LayoutView" in source
    assert "discord.ui.Container" in source
    assert "discord.ui.Section" in source
    assert "setup_v73.ACCENT" in source
    assert "setup_v73._thumbnail" in source


def test_help_v77_keeps_all_commands_visible_and_adds_navigation():
    source = HELP_V77.read_text(encoding="utf-8")

    assert "legacy._visible" in source
    assert "Voir les commandes" in source
    assert "Rechercher une commande" in source
    assert "Permission nécessaire" in source
    assert "Précédent" in source
    assert "Suivant" in source
    assert "Détails" in source


def test_help_v77_has_expected_user_facing_categories():
    source = HELP_V77.read_text(encoding="utf-8")

    for label in (
        "Modération",
        "Sécurité",
        "Tickets",
        "Bienvenue & rôles",
        "Logs",
        "Économie & niveaux",
        "Intelligence artificielle",
        "Notifications",
        "Jeux & événements",
        "Musique",
        "Utilitaires",
        "Administration",
    ):
        assert label in source


def test_help_v77_is_installed_after_official_help_runtime_is_available():
    source = SECURITY_V75.read_text(encoding="utf-8")

    assert "from . import help_components_v77 as help_v77" in source
    assert "help_v77.install(bot)" in source
