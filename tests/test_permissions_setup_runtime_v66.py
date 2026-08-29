"""Régressions V66 du panneau réellement affiché par /setup."""
from __future__ import annotations

import asyncio
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cogs import permission_setup_hardening_v65 as V66  # noqa: E402
from cogs import setup_control_center as setup_ui  # noqa: E402
from utils import access_matrix as matrix  # noqa: E402


class BrokenDB:
    async def execute(self, *args, **kwargs):
        raise RuntimeError("db intentionally unavailable")

    async def fetchone(self, *args, **kwargs):
        raise RuntimeError("db intentionally unavailable")


class Bot:
    def __init__(self):
        self.db = BrokenDB()


class RuntimeInstallTests(unittest.TestCase):
    def test_install_secures_runtime_before_optional_db_migration(self):
        bot = Bot()
        asyncio.run(V66.install(bot))
        self.assertIs(matrix.evaluate, V66.secure_evaluate)
        self.assertTrue(bot._sentrix_permission_setup_v66)

    def test_setup_constructor_has_reapply_guard(self):
        self.assertTrue(
            getattr(setup_ui.SetupView.__init__, "_sentrix_permissions_v66_constructor", False)
        )

    def test_live_render_contains_v66_marker(self):
        V66._patch_setup_surface()
        self.assertTrue(getattr(setup_ui.SetupView.render, "_sentrix_permissions_v66", False))
        self.assertTrue(getattr(setup_ui.SetupView.build_embed, "_sentrix_permissions_v66", False))


class UiContractTests(unittest.TestCase):
    def test_v66_has_no_legacy_allow_cycle(self):
        source = inspect.getsource(V66)
        self.assertNotIn("défaut → oui → non", source)
        self.assertNotIn("Tout activer", source)
        self.assertNotIn("Tout désactiver", source)
        self.assertIn("Bloquer / rétablir", source)
        self.assertIn("Activer / Désactiver", source)

    def test_visible_runtime_marker_exists(self):
        self.assertEqual(V66.RUNTIME_MARKER, "Permissions sécurisées V66")

    def test_public_commands_are_not_exposed_as_acl_targets(self):
        class FakeBot:
            commands = []

        # Le filtre V66 exclut explicitement les commandes publiques et owner-global.
        source = inspect.getsource(V66._commands_for_scope)
        self.assertIn("matrix.PUBLIC_COMMANDS", source)
        self.assertIn("matrix.OWNER_ONLY_COMMANDS", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
