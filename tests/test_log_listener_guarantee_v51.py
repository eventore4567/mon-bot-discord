from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LogListenerGuaranteeV51Tests(unittest.TestCase):
    def test_sources_compile(self):
        for rel in (
            "cogs/log_listener_guarantee_v51.py",
            "cogs/slash_error_completion_guard.py",
        ):
            path = ROOT / rel
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_logs_cog_is_registered_directly(self):
        source = (ROOT / "cogs" / "log_listener_guarantee_v51.py").read_text(encoding="utf-8")
        self.assertIn("await bot.add_cog(Logs(bot))", source)
        self.assertIn('bot.get_cog("Logs")', source)
        self.assertIn("len(cog.get_listeners())", source)

    def test_cache_failure_does_not_block_listener_registration(self):
        source = (ROOT / "cogs" / "log_listener_guarantee_v51.py").read_text(encoding="utf-8")
        cache_pos = source.index("state[\"cache_ready\"] = await _best_effort_cache(bot)")
        cog_pos = source.index("loaded, listeners = await ensure_logs_cog(bot)")
        self.assertGreater(cog_pos, cache_pos)
        self.assertIn("except Exception:", source)
        self.assertIn("return False", source)

    def test_v51_is_before_final_error_authority_and_after_live_routes(self):
        source = (ROOT / "cogs" / "slash_error_completion_guard.py").read_text(encoding="utf-8")
        route_pos = source.index("live_log_delivery_v5.install(bot)")
        listeners_pos = source.index("await log_listener_guarantee_v51.install(bot)")
        error_pos = source.index("final_error_embed_v5.install(bot)")
        self.assertGreater(listeners_pos, route_pos)
        self.assertGreater(error_pos, listeners_pos)


if __name__ == "__main__":
    unittest.main()
