from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import discord

from cogs import final_error_embed_v5 as errors_v5
from cogs import live_log_delivery_v5 as logs_v5

ROOT = Path(__file__).resolve().parents[1]


class LiveErrorsLogsV5Tests(unittest.TestCase):
    def test_sources_compile(self):
        for rel in (
            "cogs/final_error_embed_v5.py",
            "cogs/live_log_delivery_v5.py",
            "cogs/slash_error_completion_guard.py",
        ):
            path = ROOT / rel
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_error_panel_is_native_discord_embed(self):
        panel = errors_v5._panel("Commande introuvable", "La commande `+zzz` n’existe pas.")
        self.assertIsInstance(panel, discord.Embed)
        self.assertEqual(panel.title, "Commande introuvable")
        self.assertIn("+zzz", panel.description or "")
        self.assertEqual(int(panel.colour.value), errors_v5.ERROR_COLOR)

    def test_live_names_from_user_server_are_recognized(self):
        category = SimpleNamespace(name="logs")
        channels = [
            SimpleNamespace(id=1, name="logs-messages", category=category),
            SimpleNamespace(id=2, name="logs-membre", category=category),
            SimpleNamespace(id=3, name="logs-roles", category=category),
            SimpleNamespace(id=4, name="logs-vocal", category=category),
            SimpleNamespace(id=5, name="logs-modération", category=category),
            SimpleNamespace(id=6, name="logs-salons", category=category),
            SimpleNamespace(id=7, name="automod", category=category),
            SimpleNamespace(id=8, name="raidprotect-logs", category=category),
            SimpleNamespace(id=9, name="logs-protect-spam-logs", category=category),
        ]
        guild = SimpleNamespace(text_channels=channels)
        with patch("cogs.live_log_delivery_v5.log_service.validate_channel", return_value=(True, "ok")):
            expected = {
                "messages": "logs-messages",
                "members": "logs-membre",
                "roles": "logs-roles",
                "voice": "logs-vocal",
                "moderation": "logs-modération",
                "server": "logs-salons",
                "automod": "automod",
            }
            for log_type, name in expected.items():
                found = logs_v5._discover_channel(guild, log_type)
                self.assertIsNotNone(found, log_type)
                self.assertEqual(found.name, name)

    def test_protection_aliases_exist(self):
        aliases = set(logs_v5._aliases("automod"))
        self.assertIn("automod", aliases)
        self.assertIn("raidprotect-logs", aliases)
        self.assertIn("logs-protect-spam-logs", aliases)

    def test_v5_is_installed_last(self):
        source = (ROOT / "cogs" / "slash_error_completion_guard.py").read_text(encoding="utf-8")
        log_call = source.index("live_log_delivery_v5.install(bot)")
        error_call = source.index("final_error_embed_v5.install(bot)")
        v3_call = source.index("await production_embed_log_repair_v3.setup(bot)")
        self.assertGreater(log_call, v3_call)
        self.assertGreater(error_call, log_call)

    def test_raw_error_transport_bypasses_visual_wrappers(self):
        source = (ROOT / "cogs" / "final_error_embed_v5.py").read_text(encoding="utf-8")
        self.assertIn("policy._unwrap(discord.abc.Messageable.send)", source)
        self.assertIn("policy._unwrap(discord.InteractionResponse.send_message)", source)
        self.assertNotIn("utils import embeds", source)


if __name__ == "__main__":
    unittest.main()
