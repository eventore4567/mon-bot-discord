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

        # Compatibilité avec des chaînes déjà sérialisées par une ancienne couche.
        self.assertEqual(v72.state_text("ConfigState.ACTIVE"), "● ACTIF")
        self.assertEqual(v72.state_text("ConfigState.INACTIVE"), "○ INACTIF")
        self.assertEqual(v72.state_text("ConfigState.UNCONFIGURED"), "— NON CONFIGURÉ")
        self.assertEqual(v72.state_text("ConfigState.ERROR"), "! À CORRIGER")

    def test_ticket_activation_is_real_configuration_not_only_module_flag(self):
        source = V72_PATH.read_text(encoding="utf-8")
        required_contracts = (
            "create_panel(guild.id, \"Support\")",
            "add_type(guild.id, panel_id, \"Support\")",
            "guild.create_role(",
            "guild.create_category(",
            "guild.create_text_channel(",
            'set_guild_config(guild.id, "ticket_category"',
            'set_guild_config(guild.id, "ticket_log_channel"',
            "TicketPanelView(panel, types)",
            '"tickets",\n                True,',
        )
        for contract in required_contracts:
            with self.subTest(contract=contract):
                self.assertIn(contract, source)

    def test_activation_preserves_existing_ticket_values(self):
        source = V72_PATH.read_text(encoding="utf-8")
        self.assertIn("staff_role_id=COALESCE(staff_role_id,?)", source)
        self.assertIn("category_id=COALESCE(category_id,?)", source)
        self.assertIn("log_channel_id=COALESCE(log_channel_id,?)", source)
        self.assertIn("configuration est conservée", source)

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

    def test_ticket_panel_is_persistent_and_v72_reuses_it(self):
        ticket_source = (ROOT / "cogs" / "tickets.py").read_text(encoding="utf-8")
        self.assertIn("class TicketPanelView(discord.ui.View):", ticket_source)
        self.assertIn("super().__init__(timeout=None)", ticket_source)
        self.assertIn("custom_id=f\"ticket_open_btn:{ticket_type['id']}\"", ticket_source)


if __name__ == "__main__":
    unittest.main()
