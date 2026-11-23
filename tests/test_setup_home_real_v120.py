"""Contrat de l'accueil SentriX : compact et privé, sans bascule rapide."""
from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "cogs" / "setup_experience_v74.py"


def _method(name):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == "SentriXSetupV74")
    method = next(x for x in cls.body if isinstance(x, ast.AsyncFunctionDef) and x.name == name)
    return ast.unparse(method)


def test_single_menu_covers_essential_setup_and_advanced_options():
    from cogs import setup_experience_v74 as v74

    home = _method("_build_home")
    # 22/11/2026 : « refais tout le setup, plus simple ». L'accueil n'a plus le menu
    # unique de 22 entrées : six sections (SECTIONS) mènent aux mêmes pages.
    pages = {page for section in v74.SECTIONS for page in section[6]}
    for word in ("security", "logs", "tickets", "welcome", "rules_access",
                 "custom_commands", "recurring_messages", "automation", "embeds"):
        assert word in pages
    assert "discord.ui.Select(" not in home
    assert "self.refresh(interaction)" in home


def test_opening_a_page_never_activates_module():
    home = _method("_build_home")
    assert "toggle_module_switch" not in home
    assert "set_module_enabled" not in home
    assert "_set_security_profile" not in home


def test_language_reachable_without_duplicate_guide():
    from cogs import setup_experience_v74 as v74

    home = _method("_build_home")
    assert "Assistant guidé" not in home
    # 22/11/2026 : la langue est dans la section « Système » ; son sélecteur
    # s'ouvre depuis _ouvrir_page, commun à toutes les sections.
    assert any("language" in section[6] for section in v74.SECTIONS)
    assert "OfficialLanguageSelect" in _method("_ouvrir_page")


def test_setup_is_private_and_prefix_does_not_expose_controls():
    # Le chemin réellement servi est la dernière couche (cogs/setup_invitations.py,
    # final_send_setup) : /setup en éphémère, +setup en panneau public réservé à
    # son auteur (décision du 01/11/2026, PR #607), après le contrôle d'accès.
    text = (SOURCE.parent / "setup_invitations.py").read_text(encoding="utf-8")
    start = text.index("    async def final_send_setup(")
    send = text[start:text.index("    current = setup_ui.OfficialSetup.send_setup", start)]
    prefix = send[:send.index("# Discord ne sait pas envoyer un panneau éphémère")]
    # 05/11/2026 : /setup s'ouvre pour tous (lecture) ; chaque clic est contrôlé par
    # SentriXSetupV73.interaction_check (peut_configurer), plus par _can_setup à l'ouverture.
    assert "_can_setup(" not in prefix
    assert prefix.index("if guild is None or member is None") < prefix.index("panels.envoyer(target, view, ephemere=False)")
    slash = send[send.index("# Discord ne sait pas envoyer un panneau éphémère"):]
    assert "ephemere=True" in slash and "ephemere=False" not in slash
    assert "Tu n'as pas" not in send
