from __future__ import annotations

import unittest

from utils.v21_rules import (
    MARKET_MAX_QUANTITY,
    achievement_rows,
    challenge_rows,
    clean_market_query,
    market_totals,
)


class MarketRulesTests(unittest.TestCase):
    def test_market_totals_without_fee(self):
        totals = market_totals(4, 250, fee_bps=0)
        self.assertEqual(totals.subtotal, 1000)
        self.assertEqual(totals.fee, 0)
        self.assertEqual(totals.seller_receives, 1000)

    def test_market_totals_fee_rounds_up(self):
        totals = market_totals(1, 101, fee_bps=200)
        self.assertEqual(totals.subtotal, 101)
        self.assertEqual(totals.fee, 3)
        self.assertEqual(totals.seller_receives, 98)

    def test_market_quantity_guard(self):
        with self.assertRaises(ValueError):
            market_totals(MARKET_MAX_QUANTITY + 1, 1)

    def test_market_price_guard(self):
        with self.assertRaises(ValueError):
            market_totals(1, 0)

    def test_clean_market_query(self):
        self.assertEqual(clean_market_query("  Rift   Blade  "), "Rift Blade")
        with self.assertRaises(ValueError):
            clean_market_query("   ")


class ProgressionRulesTests(unittest.TestCase):
    def test_advanced_achievements_unlock(self):
        rows = achievement_rows(
            {
                "message_count": 5000,
                "current_level": 50,
                "total_money": 1_000_000,
                "reputation": 100,
                "voice_time": 360_000,
                "total_xp": 100_000,
            },
            streak=30,
            best_streak=30,
            total_claims=100,
            joined_days=365,
        )
        locked = [row["name"] for row in rows if not row["unlocked"]]
        self.assertEqual(locked, [])

    def test_achievements_do_not_unlock_early(self):
        rows = achievement_rows(
            {"message_count": 0, "current_level": 0, "total_money": 0, "reputation": 0, "voice_time": 0, "total_xp": 0}
        )
        self.assertTrue(all(not row["unlocked"] for row in rows))

    def test_challenge_percentage_is_capped(self):
        rows = challenge_rows(
            {"message_count": 5000, "current_level": 100, "total_money": 5_000_000, "reputation": 500, "voice_time": 1_000_000},
            streak=100,
        )
        self.assertTrue(all(row["percent"] == 100 for row in rows))
        self.assertTrue(all(row["complete"] for row in rows))


if __name__ == "__main__":
    unittest.main()
