from __future__ import annotations

import unittest

from cogs import community_v3


class CommunityV3PureTests(unittest.TestCase):
    def test_daily_missions_are_stable_and_unique(self):
        first = community_v3.mission_selection(123, 456, "2026-08-22")
        second = community_v3.mission_selection(123, 456, "2026-08-22")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 3)
        self.assertEqual(len({item[0] for item in first}), 3)

    def test_daily_missions_can_change_between_users(self):
        one = community_v3.mission_selection(123, 456, "2026-08-22")
        two = community_v3.mission_selection(123, 999, "2026-08-22")
        self.assertNotEqual(one, two)

    def test_ticket_priority_detects_urgent_language(self):
        summary, priority = community_v3.ticket_summary(
            "Support",
            [("Problème", "Mon compte a été hack et il y a un paiement inconnu")],
        )
        self.assertEqual(priority, "haute")
        self.assertIn("Support", summary)
        self.assertIn("hack", summary)

    def test_ticket_priority_stays_normal_for_regular_request(self):
        _summary, priority = community_v3.ticket_summary(
            "Question",
            [("Demande", "Je voudrais savoir comment obtenir le rôle membre")],
        )
        self.assertEqual(priority, "normale")

    def test_ticket_summary_is_bounded(self):
        summary, _priority = community_v3.ticket_summary(
            "Support",
            [("Long", "x" * 5000)],
        )
        self.assertLessEqual(len(summary), 750)

    def test_achievements_derive_from_existing_stats(self):
        stats = {
            "current_level": 8,
            "message_count": 2000,
            "voice_time": 12 * 3600,
            "total_money": 20_000,
            "reputation": 20,
        }
        progression = {"longest_streak": 8, "season_xp": 1800}
        achievements = community_v3.achievement_names(stats, progression)
        self.assertIn("📈 En progression", achievements)
        self.assertIn("🔥 Semaine parfaite", achievements)
        self.assertIn("🏆 Compétiteur de saison", achievements)

    def test_progress_bar_never_overflows(self):
        self.assertEqual(len(community_v3._progress_bar(9999, 250)), 10)
        self.assertEqual(len(community_v3._progress_bar(-5, 250)), 10)


if __name__ == "__main__":
    unittest.main()
