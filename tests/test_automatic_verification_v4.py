from pathlib import Path
import unittest

from cogs.automatic_verification_v4 import (
    DEFAULT_THRESHOLD,
    FACTOR_COUNT,
    MIN_THRESHOLD,
    Factor,
    clamp_threshold,
    score_factors,
)


def factors(passed: int):
    return [
        Factor(key=f"factor_{index}", label=f"Facteur {index}", passed=index < passed)
        for index in range(FACTOR_COUNT)
    ]


class AutomaticVerificationV4Tests(unittest.TestCase):
    def test_contract_is_exactly_twenty_factors(self):
        self.assertEqual(FACTOR_COUNT, 20)
        score, accepted = score_factors(factors(20))
        self.assertEqual(score, 20)
        self.assertTrue(accepted)

    def test_sixteen_passes_and_fifteen_fails(self):
        self.assertEqual(DEFAULT_THRESHOLD, 16)
        self.assertEqual(score_factors(factors(16)), (16, True))
        self.assertEqual(score_factors(factors(15)), (15, False))

    def test_threshold_can_never_be_lower_than_sixteen(self):
        self.assertEqual(MIN_THRESHOLD, 16)
        self.assertEqual(clamp_threshold(0), 16)
        self.assertEqual(clamp_threshold(15), 16)
        self.assertEqual(clamp_threshold(16), 16)
        self.assertEqual(clamp_threshold(19), 19)
        self.assertEqual(clamp_threshold(999), 20)

    def test_wrong_factor_count_fails_closed(self):
        with self.assertRaises(ValueError):
            score_factors(factors(19))
        with self.assertRaises(ValueError):
            score_factors(factors(20) + [Factor("extra", "Extra", True)])

    def test_low_score_never_contains_automatic_ban_path(self):
        source = Path("cogs/automatic_verification_v4.py").read_text(encoding="utf-8")
        evaluate = source.split("async def evaluate_member", 1)[1].split("def schedule_evaluation", 1)[0]
        low_score_branch = evaluate.split("if not passed:", 1)[1].split("unverified =", 1)[0]
        self.assertNotIn(".ban(", low_score_branch)
        self.assertNotIn(".kick(", low_score_branch)
        self.assertIn('"low_score"', low_score_branch)

    def test_membership_screening_is_deferred_then_retried(self):
        source = Path("cogs/automatic_verification_v4.py").read_text(encoding="utf-8")
        self.assertIn('getattr(member, "pending", False)', source)
        self.assertIn('reason="screening-complete"', source)
        self.assertIn("on_member_update", source)

    def test_honeypot_is_separate_from_score_decision(self):
        source = Path("cogs/automatic_verification_v4.py").read_text(encoding="utf-8")
        self.assertIn('kind="honeypot"', source)
        self.assertIn("SentriX Honeypot anti-bot", source)
        self.assertIn("Un score insuffisant ne bannit jamais", source)

    def test_natural_sentrix_trigger_still_exists(self):
        source = Path("cogs/ai.py").read_text(encoding="utf-8")
        self.assertIn("async def on_message", source)
        self.assertIn("sentrix|ssentrix|sentri|snetri|snentrix", source)
        self.assertIn("send_sentrix_reply", source)

    def test_setup_v4_exposes_real_ticket_hub(self):
        source = Path("cogs/control_center_v4.py").read_text(encoding="utf-8")
        self.assertIn("TicketSetupHubView", source)
        self.assertIn("ticket_panels_v2", source)
        self.assertIn("ticket_types", source)
        self.assertTrue("Claim • unclaim" in source or "claim / unclaim" in source)


if __name__ == "__main__":
    unittest.main()
