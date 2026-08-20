from __future__ import annotations

import unittest

from utils.accessibility import (
    closest_commands,
    human_parameter,
    match_quick_intent,
    normalize_text,
    usage_line,
)


class AccessibilityTests(unittest.TestCase):
    def test_normalize_accents_and_separators(self):
        self.assertEqual(normalize_text("ÉCONOMIE_test"), "economie-test")

    def test_command_typo_suggestions(self):
        candidates = ["balance", "ban", "blackjack", "profile", "help"]
        self.assertEqual(closest_commands("balnce", candidates)[0], "balance")
        self.assertEqual(closest_commands("profle", candidates)[0], "profile")

    def test_no_unrelated_suggestion(self):
        self.assertEqual(closest_commands("zzzzzz", ["balance", "profile"]), [])

    def test_quick_intent_tolerates_small_typos(self):
        self.assertEqual(match_quick_intent("economi"), "economy")
        self.assertEqual(match_quick_intent("profille"), "profile")
        self.assertEqual(match_quick_intent("commnde"), "home")
        self.assertEqual(match_quick_intent("jeuxx"), "games")

    def test_long_sentence_is_not_force_classified(self):
        self.assertIsNone(match_quick_intent("explique moi en détail comment fonctionne un serveur discord avec beaucoup de salons et de rôles"))

    def test_human_parameter(self):
        self.assertEqual(human_parameter("duree"), "durée")
        self.assertEqual(human_parameter("user_id"), "identifiant utilisateur")

    def test_usage_line(self):
        self.assertEqual(usage_line("+", "mute", "<membre> [duree]"), "+mute <membre> [duree]")


if __name__ == "__main__":
    unittest.main()
