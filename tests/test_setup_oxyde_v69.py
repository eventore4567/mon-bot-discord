"""Contrats de la refonte visuelle Setup V69."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
V69_PATH = ROOT / "cogs" / "setup_oxyde_v69.py"
INIT_PATH = ROOT / "cogs" / "__init__.py"
V69 = V69_PATH.read_text(encoding="utf-8")
INIT = INIT_PATH.read_text(encoding="utf-8")
TREE = ast.parse(V69)


def _class(name: str) -> ast.ClassDef:
    for node in ast.walk(TREE):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"classe {name!r} introuvable")


def _async_function(name: str) -> ast.AsyncFunctionDef:
    for node in ast.walk(TREE):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"fonction async {name!r} introuvable")


class SetupOxydeV69Tests(unittest.TestCase):
    def test_v69_is_loaded_after_v68(self):
        self.assertIn("install_setup_oxyde_v69", INIT)
        self.assertLess(
            INIT.index('await _run_installer("Setup simple et help V68"'),
            INIT.index('await _run_installer("Control Center visuel V69"'),
        )

    def test_wide_control_center_contract(self):
        self.assertIn("WIDE_RULE", V69)
        self.assertIn("Control Center", V69)
        self.assertIn("SHOW_THUMBNAILS = False", V69)
        self.assertIn("Choisir une page du Control Center", V69)

    def test_single_navigation_select_includes_home(self):
        node = _class("OxydePageSelect")
        text = ast.unparse(node)
        self.assertIn("Accueil", text)
        self.assertIn("__home__", text)
        self.assertIn("row=0", text)

    def test_permissions_are_only_one_toggle_visually(self):
        node = _class("PermissionToggleButton")
        text = ast.unparse(node)
        self.assertIn("Activer / Désactiver", text)
        self.assertIn('"permissions"', text)
        self.assertNotIn("RoleSelect", text)
        self.assertNotIn("Commande à restreindre", V69)
        self.assertNotIn("Groupe de commandes", V69)
        self.assertNotIn("Rôle à restreindre", V69)

    def test_security_is_only_one_toggle_visually(self):
        node = _class("SecurityToggleButton")
        text = ast.unparse(node)
        self.assertIn("Activer / Désactiver", text)
        self.assertIn("automod_settings", text)
        self.assertIn("AUTOMOD", text)

    def test_permission_page_explicitly_keeps_discord_security(self):
        node = _async_function("_build_permissions")
        text = ast.unparse(node)
        self.assertIn("TOUJOURS OBLIGATOIRES", text)
        self.assertIn("permissions Discord réelles", text)
        self.assertIn("Jeux, argent, banque, classements, invitations, niveaux", text)

    def test_v69_reaffirms_v68_permission_runtime(self):
        self.assertIn("v68._install_permission_runtime()", V69)
        self.assertNotIn("matrix.evaluate =", V69)

    def test_existing_business_controls_are_preserved(self):
        # V69 appelle d'abord le renderer existant : modération/logs/tickets/IA gardent
        # leurs callbacks et leurs écritures DB, seule leur présentation est nettoyée.
        self.assertIn("previous_render(self)", V69)
        self.assertIn("previous_build(self)", V69)

    def test_old_home_buttons_are_removed(self):
        self.assertIn('{"accueil", "actualiser", "fermer"}', V69)

    def test_pages_are_rendered_one_at_a_time(self):
        node = _async_function("build_embed_v69")
        text = ast.unparse(node)
        self.assertIn("self.category is None", text)
        self.assertIn('self.category == "permissions"', text)
        self.assertIn('self.category == "security"', text)
        self.assertIn("_build_page", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
