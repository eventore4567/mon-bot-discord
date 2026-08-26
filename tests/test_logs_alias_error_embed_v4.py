from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

from cogs import generated_logs_sync as sync

ROOT = Path(__file__).resolve().parents[1]


class LogAliasAndErrorEmbedV4Tests(unittest.TestCase):
    def test_sources_compile(self):
        for rel in (
            "cogs/generated_logs_sync.py",
            "cogs/slash_error_completion_guard.py",
        ):
            path = ROOT / rel
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_create_logs_names_are_all_recognized(self):
        # Contrat critique : même si SQLite repart vide, les sept salons créés par
        # Configuration.create_log_channels doivent suffire à reconstruire le routage.
        created_names = {
            "server": "logs-serveur",
            "messages": "logs-messages",
            "members": "logs-membre",
            "voice": "logs-vocal",
            "roles": "logs-roles",
            "moderation": "logs-moderation",
            "automod": "logs-securite",
        }
        category = SimpleNamespace(name="📡 SentriX — Logs")
        channels = [
            SimpleNamespace(name=name, category=category)
            for name in created_names.values()
        ]
        guild = SimpleNamespace(text_channels=channels)

        recovered = 0
        for log_type, channel_name in created_names.items():
            channel = sync._find_log_channel(guild, log_type)
            self.assertIsNotNone(channel, log_type)
            self.assertEqual(channel.name, channel_name)
            recovered += 1
        self.assertEqual(recovered, 7)

    def test_historical_accented_plural_names_are_recognized(self):
        category = SimpleNamespace(name="LOGS")
        names = {
            "members": "logs-membres",
            "voice": "logs-vocaux",
            "roles": "logs-rôles",
            "moderation": "logs-modération",
            "automod": "logs-sécurité",
        }
        guild = SimpleNamespace(
            text_channels=[SimpleNamespace(name=name, category=category) for name in names.values()]
        )
        for log_type, channel_name in names.items():
            self.assertEqual(sync._find_log_channel(guild, log_type).name, channel_name)

    def test_normalizer_removes_accents_and_visual_separators(self):
        self.assertEqual(sync._plain("📡・logs-modération"), "logs-moderation")
        self.assertEqual(sync._plain("logs_sécurité"), "logs-securite")

    def test_slash_finalization_fallback_is_direct_embed(self):
        source = (ROOT / "cogs" / "slash_error_completion_guard.py").read_text(encoding="utf-8")
        self.assertIn('embed=embeds.error(_ERROR_FALLBACK, title="Erreur de commande")', source)
        self.assertIn("content=None", source)
        self.assertNotIn("content=_ERROR_FALLBACK", source)
        self.assertNotIn("embeds=[]", source)


if __name__ == "__main__":
    unittest.main()
