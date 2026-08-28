"""Non-régression du mode IA sans mention."""
from __future__ import annotations

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "cogs" / "ai_bare_chat_v3.py"


class BareAiSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SOURCE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.text)

    def test_module_parses(self):
        self.assertIsInstance(self.tree, ast.Module)

    def test_bare_mode_is_disabled_by_default(self):
        self.assertIn("enabled INTEGER NOT NULL DEFAULT 0", self.text)

    def test_bare_mode_requires_explicit_channel(self):
        self.assertIn('message.channel.id not in values["channel_ids"]', self.text)
        self.assertIn("ai_bare_chat_channels_v3", self.text)

    def test_prefix_and_historical_triggers_are_not_intercepted(self):
        self.assertIn("content.startswith(prefix)", self.text)
        self.assertIn("message.mentions", self.text)
        self.assertIn("_NAME_TRIGGER.match(content)", self.text)

    def test_runtime_respects_ai_module_and_feature_switch(self):
        self.assertIn('module_enabled(self.bot, message.guild.id, "ai")', self.text)
        self.assertIn('features["natural_enabled"]', self.text)
        self.assertIn('settings["enabled"]', self.text)

    def test_runtime_respects_existing_channel_and_role_limits(self):
        self.assertIn("ai_service.is_channel_allowed", self.text)
        self.assertIn("ai_service.is_role_allowed", self.text)

    def test_setup_exposes_bare_chat_manager(self):
        self.assertIn('label="Parler sans mention"', self.text)
        self.assertIn("Écrire `salut` suffit uniquement dans ces salons.", self.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
