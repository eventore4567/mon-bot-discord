from __future__ import annotations

import asyncio
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

from discord.ext import commands

from cogs import final_interaction_policy as policy
from cogs import production_embed_log_repair_v3 as v3

ROOT = Path(__file__).resolve().parents[1]


class _DummyBot:
    def __init__(self):
        self.seen_roots: list[str] = []

    async def invoke(self, _ctx):
        self.seen_roots.append(policy._COMMAND_ROOT.get())
        return "ok"


async def _noop(_ctx):
    return None


class ProductionEmbedLogRepairV3Tests(unittest.TestCase):
    def test_sources_compile_and_last_railway_guard_loads_v3(self):
        for rel in (
            "cogs/production_embed_log_repair_v3.py",
            "cogs/slash_error_completion_guard.py",
        ):
            path = ROOT / rel
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        guard = (ROOT / "cogs" / "slash_error_completion_guard.py").read_text(encoding="utf-8")
        self.assertIn("production_embed_log_repair_v3", guard)
        self.assertIn("await production_embed_log_repair_v3.setup(bot)", guard)

    def test_prefix_invoke_keeps_command_root_for_direct_channel_sends(self):
        bot = _DummyBot()
        command = commands.Command(_noop, name="probe")
        ctx = SimpleNamespace(command=command)

        v3._install_prefix_execution_context(bot)
        result = asyncio.run(bot.invoke(ctx))

        self.assertEqual(result, "ok")
        self.assertEqual(bot.seen_roots, ["probe"])
        self.assertEqual(policy._COMMAND_ROOT.get(), "")
        self.assertTrue(getattr(bot, "sentrix_embed_log_repair_v3_state")["prefix_execution_context"])

    def test_log_v3_is_a_new_one_time_migration(self):
        source = (ROOT / "cogs" / "production_embed_log_repair_v3.py").read_text(encoding="utf-8")
        self.assertIn('production_embed_log_repair_v3_force_routes', source)
        self.assertIn('if not applied and configured:', source)
        self.assertIn('await log_service.set_log_enabled(bot, guild.id, log_type, True)', source)
        self.assertIn('await _mark_migration(bot, guild.id)', source)

    def test_v3_reuses_official_log_transport_only(self):
        source = (ROOT / "cogs" / "production_embed_log_repair_v3.py").read_text(encoding="utf-8")
        self.assertIn('bot.get_cog("Logs")', source)
        self.assertIn('log_service.validate_channel', source)
        self.assertNotIn('discord.Client(', source)


if __name__ == "__main__":
    unittest.main()
