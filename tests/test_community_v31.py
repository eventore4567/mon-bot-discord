from __future__ import annotations

import unittest

from cogs import community_v31


class CommunityV31Tests(unittest.TestCase):
    def test_ticket_topic_waiting_high_priority(self):
        topic = community_v31.ticket_topic(42, "haute")
        self.assertIn("Ticket #42", topic)
        self.assertIn("PRIORITÉ HAUTE", topic)
        self.assertIn("EN ATTENTE", topic)

    def test_ticket_topic_claimed(self):
        topic = community_v31.ticket_topic(7, "normale", "Tomioka")
        self.assertIn("PRIS EN CHARGE", topic)
        self.assertIn("Tomioka", topic)
        self.assertLessEqual(len(topic), 1024)

    def test_achievement_catalog_unlocks_expected_thresholds(self):
        stats = {
            "current_level": 5,
            "message_count": 1000,
            "voice_time": 10 * 3600,
            "total_money": 10000,
            "reputation": 10,
        }
        progression = {"longest_streak": 7, "season_xp": 3000}
        catalog = community_v31.achievement_catalog(stats, progression)
        self.assertTrue(all(item["unlocked"] for item in catalog))
        self.assertEqual(len(catalog), 8)

    def test_achievement_catalog_keeps_locked_goals_visible(self):
        catalog = community_v31.achievement_catalog({}, {})
        self.assertTrue(all(not item["unlocked"] for item in catalog))
        self.assertTrue(all(item["hint"] for item in catalog))


if __name__ == "__main__":
    unittest.main()
