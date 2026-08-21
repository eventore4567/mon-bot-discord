from __future__ import annotations

import types
import unittest

from cogs import runtime_quality_v25, user_facing_hygiene


class UserFacingV25Tests(unittest.TestCase):
    def test_internal_context_is_never_displayed(self):
        self.assertEqual(
            user_facing_hygiene.sanitize_usage_text("+gamble <ctx> <montant>"),
            "+gamble <montant>",
        )
        self.assertEqual(
            user_facing_hygiene.sanitize_usage_text("+ban [context] <membre> [raison]"),
            "+ban <membre> [raison]",
        )

    def test_cooldown_is_human_readable(self):
        self.assertEqual(user_facing_hygiene._cooldown_text(8), "8 s")
        self.assertEqual(user_facing_hygiene._cooldown_text(65), "1 min 5 s")
        self.assertEqual(user_facing_hygiene._cooldown_text(3665), "1 h 1 min 5 s")
        self.assertEqual(user_facing_hygiene._cooldown_text(90061), "1 j 1 h")

    def test_int_annotation_accepts_resolved_or_future_form(self):
        self.assertTrue(runtime_quality_v25._annotation_is_int(int))
        self.assertTrue(runtime_quality_v25._annotation_is_int("int"))
        self.assertFalse(runtime_quality_v25._annotation_is_int(str))


class CreatorCacheV25Tests(unittest.IsolatedAsyncioTestCase):
    async def test_negative_results_are_cached_but_positive_results_are_not(self):
        class FakeDB:
            def __init__(self):
                self.calls: dict[int, int] = {}

            async def is_bot_creator(self, user_id: int) -> bool:
                uid = int(user_id)
                self.calls[uid] = self.calls.get(uid, 0) + 1
                return uid == 99

        db = FakeDB()
        bot = types.SimpleNamespace(db=db)
        runtime_quality_v25._install_negative_creator_cache(bot)

        self.assertFalse(await db.is_bot_creator(10))
        self.assertFalse(await db.is_bot_creator(10))
        self.assertEqual(db.calls[10], 1, "un non-propriétaire doit utiliser le cache négatif")

        self.assertTrue(await db.is_bot_creator(99))
        self.assertTrue(await db.is_bot_creator(99))
        self.assertEqual(db.calls[99], 2, "un propriétaire positif ne doit jamais être mis en cache")

        stats = bot._sentrix_v25_creator_cache_stats
        self.assertGreaterEqual(stats["hits"], 1)
        self.assertGreaterEqual(stats["misses"], 3)


if __name__ == "__main__":
    unittest.main()
