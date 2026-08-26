from __future__ import annotations

import ast
from pathlib import Path
import unittest

import discord
from discord.ext import commands

import main
from cogs import final_interaction_policy as policy
from cogs import production_embed_log_repair as repair

ROOT = Path(__file__).resolve().parents[1]


class ProductionEmbedLogRepairTests(unittest.TestCase):
    def test_sources_compile_and_last_guard_loads_repair(self):
        for rel in (
            "cogs/production_embed_log_repair.py",
            "cogs/slash_error_completion_guard.py",
        ):
            path = ROOT / rel
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        guard = (ROOT / "cogs" / "slash_error_completion_guard.py").read_text(encoding="utf-8")
        self.assertIn("production_embed_log_repair", guard)
        self.assertIn("await production_embed_log_repair.setup(bot)", guard)

    def test_mass_recovery_only_for_old_all_disabled_state(self):
        self.assertTrue(repair._should_mass_recover(7, 0, False))
        self.assertTrue(repair._should_mass_recover(1, 0, False))
        self.assertFalse(repair._should_mass_recover(0, 0, False))
        self.assertFalse(repair._should_mass_recover(7, 1, False))
        self.assertFalse(repair._should_mass_recover(7, 0, True))

    def test_direct_prefix_transport_is_installed_on_real_sentrix_context(self):
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="+", intents=intents)
        try:
            repair._force_all_command_embeds()
            repair._install_direct_prefix_transport(bot)
            self.assertTrue(getattr(main.SentriXContext.send, "_sentrix_direct_embed_transport_v2", False))
            self.assertFalse(policy._plain_root("sentrix"))
            self.assertFalse(policy._plain_root("ping"))
        finally:
            # No network connection is opened; close() is not required for this sync smoke.
            pass

    def test_command_payload_is_embed_even_for_sentrix_root(self):
        from cogs import command_embed_invariant as invariant

        repair._force_all_command_embeds()
        args, kwargs = invariant._normalize_command_payload(
            ("Réponse de commande.",),
            {},
            root="sentrix",
        )
        self.assertIsNone(args[0])
        self.assertIsInstance(kwargs.get("embed"), discord.Embed)
        self.assertIn("Réponse de commande.", str(kwargs["embed"].description))

    def test_prefix_transport_source_disables_author_ping(self):
        source = (ROOT / "cogs" / "production_embed_log_repair.py").read_text(encoding="utf-8")
        self.assertIn('kwargs["mention_author"] = False', source)
        self.assertNotIn('kwargs["mention_author"] = True', source)

    def test_log_repair_has_persistent_one_time_marker(self):
        source = (ROOT / "cogs" / "production_embed_log_repair.py").read_text(encoding="utf-8")
        self.assertIn("sentrix_runtime_migrations", source)
        self.assertIn("production_embed_log_repair_v2", source)
        self.assertIn("await log_service.set_log_enabled", source)
        self.assertIn('bot.get_cog("Logs")', source)


if __name__ == "__main__":
    unittest.main()
