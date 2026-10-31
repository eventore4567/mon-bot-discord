"""Compteurs globaux publics : membres cumulés et utilisateurs réels des commandes."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.stats import Stats


class UsageStatsTests(unittest.IsolatedAsyncioTestCase):
    def _cog(self, result=None, error=None):
        fetchone = AsyncMock(side_effect=error) if error else AsyncMock(return_value=result)
        bot = SimpleNamespace(
            guilds=[SimpleNamespace(member_count=100), SimpleNamespace(member_count=50),
                    SimpleNamespace(member_count=None)],
            db=SimpleNamespace(fetchone=fetchone),
        )
        return Stats(bot), fetchone

    async def test_comptes_uniques_distincts_des_membres_cumules(self):
        cog, fetchone = self._cog({"n": 22})
        self.assertEqual(await cog._global_usage(), (3, 150, 22))
        fetchone.assert_awaited_once()
        query = fetchone.await_args.args[0]
        self.assertIn("COUNT(DISTINCT user_id)", query)
        self.assertIn("command_logs", query)

    async def test_cache_limite_les_requetes(self):
        cog, fetchone = self._cog({"n": 22})
        self.assertEqual(await cog._global_usage(), (3, 150, 22))
        self.assertEqual(await cog._global_usage(), (3, 150, 22))
        fetchone.assert_awaited_once()

    async def test_base_indisponible_ne_devient_pas_zero(self):
        cog, _ = self._cog(error=RuntimeError("db down"))
        self.assertEqual(await cog._global_usage(), (3, 150, None))


if __name__ == "__main__":
    unittest.main()
