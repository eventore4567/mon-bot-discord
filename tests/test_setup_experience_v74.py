from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
V74_PATH = ROOT / "cogs" / "setup_experience_v74.py"
INIT_PATH = ROOT / "cogs" / "__init__.py"


class SetupExperienceV74Tests(unittest.TestCase):
    def test_source_compiles(self):
        source = V74_PATH.read_text(encoding="utf-8")
        ast.parse(source, filename=str(V74_PATH))

    def test_security_page_is_single_profile_toggle(self):
        source = V74_PATH.read_text(encoding="utf-8")
        self.assertIn('if page == "security"', source)
        self.assertIn("Activer la sécurité", source)
        self.assertIn("Désactiver la sécurité", source)
        self.assertIn("_set_security_profile", source)
        self.assertNotIn("AdvancedAutomodSelect", source)
        self.assertNotIn("RaidIntensitySelect", source)

    def test_permissions_are_native_and_manual_page_hidden(self):
        source = V74_PATH.read_text(encoding="utf-8")
        order_block = source.split("CATEGORY_ORDER = (", 1)[1].split(")", 1)[0]
        self.assertNotIn('"permissions"', order_block)
        self.assertIn("permissions Discord réelles", source)
        self.assertIn("role.permissions", source)

    def test_tickets_have_quick_and_full_configuration(self):
        source = V74_PATH.read_text(encoding="utf-8")
        self.assertIn("ensure_ticket_configuration", source)
        self.assertIn("TicketSetupHubView", source)
        self.assertIn("Configuration rapide / réparer", source)
        self.assertIn("Tout personnaliser", source)
        self.assertIn("25 options par panel", source)
        self.assertIn("interaction.user.add_roles", source)

    def test_moderation_role_is_clear_and_sanction_badges_are_real(self):
        source = V74_PATH.read_text(encoding="utf-8")
        self.assertIn("Le vieux **« Rôle staff »** n’est plus demandé", source)
        self.assertIn("MODERATION_PROFILES", source)
        self.assertIn("Rôle à donner pendant un mute", source)
        self.assertIn("Rôle à donner après un warn", source)
        self.assertIn("_sync_sanction_badge", source)
        self.assertIn('action == "unmute"', source)

    def test_v74_is_installed_after_v73(self):
        source = INIT_PATH.read_text(encoding="utf-8")
        self.assertIn("install_setup_experience_v74", source)
        v73 = source.index('"Control Center Components V2 V73"')
        v74 = source.index('"Setup Experience V74"')
        finalized = source.index("bot._sentrix_runtime_finalized_clean = True")
        self.assertLess(v73, v74)
        self.assertLess(v74, finalized)


if __name__ == "__main__":
    unittest.main()
