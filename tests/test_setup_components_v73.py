from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
V73_PATH = ROOT / "cogs" / "setup_components_v73.py"
INIT_PATH = ROOT / "cogs" / "__init__.py"


class SetupComponentsV73Tests(unittest.TestCase):
    def test_source_compiles(self):
        ast.parse(V73_PATH.read_text(encoding="utf-8"), filename=str(V73_PATH))

    def test_components_v2_shell_matches_setup_contract(self):
        source = V73_PATH.read_text(encoding="utf-8")
        for contract in (
            "discord.ui.LayoutView",
            "discord.ui.Container",
            "discord.ui.Section",
            "discord.ui.TextDisplay",
            "discord.ui.Thumbnail",
            "discord.ui.ActionRow",
            'label="Configurer"',
            "setup_ui.SetupView(self.bot, self.guild, self.author_id)",
            "backend.refresh = types.MethodType",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, source)

    def test_all_final_setup_categories_are_present(self):
        source = V73_PATH.read_text(encoding="utf-8")
        for category in (
            "moderation", "security", "tickets", "welcome", "roles",
            "logs", "levels", "notifications", "ai", "permissions",
        ):
            with self.subTest(category=category):
                self.assertIn(f'"{category}"', source)

    def test_existing_data_is_reused_not_recreated(self):
        source = V73_PATH.read_text(encoding="utf-8")
        self.assertNotIn("DELETE FROM", source)
        self.assertNotIn("DROP TABLE", source)
        self.assertNotIn("CREATE TABLE", source)
        self.assertIn("_summary_from_embed", source)
        self.assertIn("legacy_panel = await self.backend.build_embed()", source)

    def test_v73_replaces_only_official_setup_sender(self):
        source = V73_PATH.read_text(encoding="utf-8")
        self.assertIn("setup_ui.OfficialSetup.send_setup = _send_setup_v73", source)
        self.assertNotIn("setup_ui.SetupView =", source)

    def test_v73_is_final_visual_setup_layer(self):
        source = INIT_PATH.read_text(encoding="utf-8")
        self.assertIn("install_setup_components_v73", source)
        v72 = source.index('"Tickets auto-configurables et états Setup V72"')
        v73 = source.index('"Control Center Components V2 V73"')
        finalized = source.index("bot._sentrix_runtime_finalized_clean = True")
        self.assertLess(v72, v73)
        self.assertLess(v73, finalized)

    def test_components_v2_edits_clear_legacy_embed_payloads(self):
        source = V73_PATH.read_text(encoding="utf-8")
        self.assertIn("content=None", source)
        self.assertIn("embed=None", source)
        self.assertIn("attachments=[]", source)


if __name__ == "__main__":
    unittest.main()
