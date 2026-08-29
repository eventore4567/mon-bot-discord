"""Contrats de la finition visuelle Setup V70."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "cogs" / "setup_polish_v70.py"
LOADER = ROOT / "cogs" / "__init__.py"
SOURCE = MODULE.read_text(encoding="utf-8")
INIT = LOADER.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _function(name: str):
    for node in ast.walk(TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"fonction {name!r} introuvable")


class SetupPolishV70Tests(unittest.TestCase):
    def test_v70_compiles_and_is_visual_only(self):
        ast.parse(SOURCE, filename=str(MODULE))
        self.assertIn("Control Center V70", SOURCE)
        self.assertNotIn("matrix.evaluate =", SOURCE)
        self.assertNotIn("DELETE FROM command_role_permissions", SOURCE)
        self.assertNotIn("INSERT INTO command_role_permissions", SOURCE)

    def test_v70_loads_after_v69(self):
        self.assertIn("install_setup_polish_v70", INIT)
        final = INIT.index("async def finalize_runtime")
        v69 = INIT.index("install_setup_oxyde_v69", final)
        v70 = INIT.index("install_setup_polish_v70", final)
        self.assertLess(v69, v70)

    def test_home_is_compact_and_scannable(self):
        fn = _function("_home")
        text = ast.unparse(fn)
        self.assertIn("ESSENTIEL", SOURCE)
        self.assertIn("COMMUNAUTÉ", SOURCE)
        self.assertIn("SERVICES", SOURCE)
        self.assertIn("à corriger", text)
        self.assertIn("NAVIGATION", text)
        self.assertIn("inline=True", text)

    def test_navigation_marks_current_page(self):
        self.assertIn("default=current ==", SOURCE)
        self.assertIn("Page :", SOURCE)
        self.assertIn("V70PageSelect", SOURCE)

    def test_states_are_immediately_visible(self):
        fn = _function("_state")
        text = ast.unparse(fn)
        self.assertIn("● ACTIF", text)
        self.assertIn("○ INACTIF", text)
        self.assertIn("! À CORRIGER", text)
        self.assertIn("— NON CONFIGURÉ", text)

    def test_permissions_and_security_stay_simple(self):
        permissions = ast.unparse(_function("_permissions"))
        security = ast.unparse(_function("_security"))
        self.assertIn("SÉCURITÉ DISCORD", permissions)
        self.assertIn("permissions Discord réelles", permissions)
        self.assertIn("PROFIL", security)
        self.assertIn("AUTOMATIQUE", security)
        self.assertIn("Activer / Désactiver", SOURCE)

    def test_generic_pages_share_one_structure(self):
        fn = _function("_generic_page")
        text = ast.unparse(fn)
        self.assertIn("ÉTAT", text)
        self.assertIn("CONFIGURATION", text)
        self.assertIn("_add_details", text)
        self.assertIn("_add_bot_permissions", text)

    def test_bot_permissions_are_collapsed_when_ok(self):
        fn = _function("_add_bot_permissions")
        text = ast.unparse(fn)
        self.assertIn("MANQUANT", text)
        self.assertIn("TOUT EST PRÊT", text)

    def test_business_callbacks_are_not_replaced(self):
        # V70 enveloppe les surfaces V69 existantes au lieu de recoder leurs callbacks.
        self.assertIn("previous_render(self)", SOURCE)
        self.assertIn("await previous_prepare(self)", SOURCE)
        self.assertIn("source = await previous_build(self)", SOURCE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
