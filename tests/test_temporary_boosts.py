from __future__ import annotations

import os
import tempfile
import time
import unittest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from database.db import Database
from utils import temporary_boosts


class TemporaryBoostTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self._tmpdir.name, "boosts.db"))
        await self.db.connect()
        self.guild_id = 10
        self.user_id = 20

    async def asyncTearDown(self):
        await self.db._conn.close()
        self._tmpdir.cleanup()

    async def test_quest_boost_is_persistent_and_applies_money_and_xp(self):
        boost, granted = await temporary_boosts.grant_quest_boost(
            self.db,
            self.guild_id,
            self.user_id,
            money_multiplier=1.2,
            xp_multiplier=1.2,
            duration_seconds=900,
        )
        self.assertTrue(granted)
        self.assertEqual(boost.money_multiplier, 1.2)
        self.assertEqual(boost.xp_multiplier, 1.2)

        money, active_money = await temporary_boosts.apply_money_boost(
            self.db, self.guild_id, self.user_id, 100
        )
        xp, active_xp = await temporary_boosts.apply_xp_boost(
            self.db, self.guild_id, self.user_id, 50
        )
        self.assertEqual(money, 120)
        self.assertEqual(xp, 60)
        self.assertIsNotNone(active_money)
        self.assertIsNotNone(active_xp)

    async def test_same_or_weaker_quest_never_extends_active_boost(self):
        now = 1_000_000
        first, granted = await temporary_boosts.grant_quest_boost(
            self.db,
            self.guild_id,
            self.user_id,
            money_multiplier=1.3,
            xp_multiplier=1.3,
            duration_seconds=1200,
            now_ts=now,
        )
        self.assertTrue(granted)

        second, granted_again = await temporary_boosts.grant_quest_boost(
            self.db,
            self.guild_id,
            self.user_id,
            money_multiplier=1.2,
            xp_multiplier=1.2,
            duration_seconds=1800,
            now_ts=now + 60,
        )
        self.assertFalse(granted_again)
        self.assertEqual(second.expires_at, first.expires_at)
        self.assertEqual(second.money_multiplier, 1.3)

    async def test_stronger_quest_replaces_active_boost_without_stacking_multipliers(self):
        now = 2_000_000
        await temporary_boosts.grant_quest_boost(
            self.db,
            self.guild_id,
            self.user_id,
            money_multiplier=1.1,
            xp_multiplier=1.1,
            duration_seconds=600,
            now_ts=now,
        )
        stronger, granted = await temporary_boosts.grant_quest_boost(
            self.db,
            self.guild_id,
            self.user_id,
            money_multiplier=1.3,
            xp_multiplier=1.3,
            duration_seconds=1200,
            now_ts=now + 30,
        )
        self.assertTrue(granted)
        self.assertEqual(stronger.money_multiplier, 1.3)
        self.assertEqual(stronger.xp_multiplier, 1.3)
        self.assertLessEqual(stronger.remaining(now + 30), temporary_boosts.MAX_DURATION_SECONDS)

    async def test_expired_boost_is_removed_automatically(self):
        now = 3_000_000
        await temporary_boosts.grant_quest_boost(
            self.db,
            self.guild_id,
            self.user_id,
            money_multiplier=1.2,
            xp_multiplier=1.2,
            duration_seconds=60,
            now_ts=now,
        )
        active = await temporary_boosts.get_active_boost(
            self.db, self.guild_id, self.user_id, now_ts=now + 61
        )
        self.assertIsNone(active)
        row = await self.db.fetchone(
            "SELECT * FROM temporary_boosts WHERE guild_id=? AND user_id=?",
            (self.guild_id, self.user_id),
        )
        self.assertIsNone(row)

    def test_quest_risk_tiers_are_bounded(self):
        self.assertEqual(temporary_boosts.quest_boost_for_risk(0.75)[:2], (1.1, 1.1))
        self.assertEqual(temporary_boosts.quest_boost_for_risk(1.05)[:2], (1.2, 1.2))
        self.assertEqual(temporary_boosts.quest_boost_for_risk(1.9)[:2], (1.3, 1.3))


if __name__ == "__main__":
    unittest.main()
