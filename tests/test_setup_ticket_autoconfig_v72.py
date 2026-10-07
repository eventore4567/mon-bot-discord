from __future__ import annotations

import ast
from pathlib import Path
import unittest

from cogs import setup_control_center as setup_ui
from cogs import setup_ticket_autoconfig_v72 as v72

ROOT = Path(__file__).resolve().parents[1]
V72_PATH = ROOT / "cogs" / "setup_ticket_autoconfig_v72.py"
INIT_PATH = ROOT / "cogs" / "__init__.py"


class SetupTicketAutoconfigV72Tests(unittest.TestCase):
    def test_source_compiles(self):
        source = V72_PATH.read_text(encoding="utf-8")
        ast.parse(source, filename=str(V72_PATH))

    def test_config_states_never_leak_python_enum_repr(self):
        expected = {
            setup_ui.ConfigState.ACTIVE: "● ACTIF",
            setup_ui.ConfigState.INACTIVE: "○ INACTIF",
            setup_ui.ConfigState.UNCONFIGURED: "— NON CONFIGURÉ",
            setup_ui.ConfigState.ERROR: "! À CORRIGER",
        }
        for source, rendered in expected.items():
            with self.subTest(source=source):
                value = v72.state_text(source)
                self.assertEqual(value, rendered)
                self.assertNotIn("ConfigState", value)

    def test_ticket_activation_never_creates_discord_resources(self):
        source = V72_PATH.read_text(encoding="utf-8")
        forbidden = (
            "guild.create_role(",
            "guild.create_category(",
            "guild.create_text_channel(",
        )
        for marker in forbidden:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, source)

    def test_ticket_activation_never_creates_panel_or_type(self):
        source = V72_PATH.read_text(encoding="utf-8")
        ensure_start = source.index("async def ensure_ticket_configuration")
        ensure_end = source.index("\n\nasync def _ack", ensure_start)
        block = source[ensure_start:ensure_end]
        self.assertNotIn("create_panel(", block)
        self.assertNotIn("add_type(", block)
        self.assertNotIn("panels.envoyer(", block)
        self.assertIn("Aucun panel Tickets n'est configuré", block)
        self.assertIn("Aucun type de ticket n'est configuré", block)

    def test_deleted_panel_is_not_recreated(self):
        source = V72_PATH.read_text(encoding="utf-8")
        start = source.index("async def _require_existing_panel_message")
        end = source.index("\n\nasync def ensure_ticket_configuration", start)
        block = source[start:end]
        self.assertIn("await channel.fetch_message", block)
        self.assertIn("Le panel Tickets configuré a été supprimé", block)
        self.assertNotIn("panels.envoyer(", block)

    def test_activation_only_enables_after_existing_config_is_valid(self):
        source = V72_PATH.read_text(encoding="utf-8")
        start = source.index("async def ensure_ticket_configuration")
        end = source.index("\n\nasync def _ack", start)
        block = source[start:end]
        self.assertIn("_require_existing_panel_message", block)
        self.assertIn("set_module_enabled(", block)
        self.assertIn('"tickets",\n            True,', block)

    def test_old_ticket_panels_obey_module_off_state(self):
        source = V72_PATH.read_text(encoding="utf-8")
        self.assertIn("ticket_runtime.Tickets.start_ticket_flow = start_ticket_flow_v72", source)
        self.assertIn('module_enabled(self.bot, guild.id, "tickets")', source)
        self.assertIn("Le système de tickets est actuellement désactivé", source)

    def test_v72_only_replaces_ticket_toggle(self):
        source = V72_PATH.read_text(encoding="utf-8")
        self.assertIn('getattr(self, "category", None) != "tickets"', source)
        self.assertIn('getattr(child, "module", None) == "tickets"', source)
        self.assertNotIn('getattr(child, "module", None) == "security"', source)

    def test_v72_is_installed_after_security_v71(self):
        source = INIT_PATH.read_text(encoding="utf-8")
        self.assertIn("install_setup_ticket_autoconfig_v72", source)
        security = source.index('"Sécurité avancée et vérification V71"')
        tickets = source.index('"Tickets auto-configurables et états Setup V72"')
        finalized = source.index("bot._sentrix_runtime_finalized_clean = True")
        self.assertLess(security, tickets)
        self.assertLess(tickets, finalized)


if __name__ == "__main__":
    unittest.main()
