from pathlib import Path
import unittest

from cogs.automatic_verification_v5 import (
    DEFAULT_THRESHOLD,
    FACTOR_COUNT,
    GROUP_BUDGETS,
    SIGNAL_COUNT,
    Signal,
    score_breakdown,
    score_signals,
)


GROUP_COUNTS = {
    "identity": 6,
    "maturity": 6,
    "session": 5,
    "roles": 4,
    "history": 7,
    "raid": 5,
    "behavior": 5,
    "trust": 2,
}


def signals(*, passed=True, unavailable_groups=()):
    result = []
    for group, count in GROUP_COUNTS.items():
        for index in range(count):
            unavailable = group in unavailable_groups
            result.append(
                Signal(
                    key=f"{group}_{index}",
                    label=f"{group} {index}",
                    passed=None if unavailable else passed,
                    group=group,
                    available=not unavailable,
                )
            )
    return result


class AutomaticVerificationV5Tests(unittest.TestCase):
    def test_contract_is_40_signals_but_score_stays_on_20(self):
        self.assertEqual(SIGNAL_COUNT, 40)
        self.assertEqual(FACTOR_COUNT, 20)
        self.assertEqual(sum(GROUP_COUNTS.values()), 40)
        self.assertAlmostEqual(sum(GROUP_BUDGETS.values()), 20.0)
        score, accepted = score_signals(signals(passed=True), DEFAULT_THRESHOLD)
        self.assertEqual(score, 20.0)
        self.assertTrue(accepted)

    def test_correlated_account_age_is_capped_to_two_points(self):
        sample = signals(passed=True)
        for index, signal in enumerate(sample):
            if signal.group == "maturity":
                sample[index] = Signal(
                    key=signal.key,
                    label=signal.label,
                    passed=False,
                    group=signal.group,
                )
        breakdown = score_breakdown(sample)
        self.assertEqual(breakdown["maturity"], 0.0)
        self.assertEqual(GROUP_BUDGETS["maturity"], 2.0)
        self.assertGreaterEqual(sum(breakdown.values()), 18.0)

    def test_unknown_information_is_neutral_not_failure(self):
        sample = signals(passed=True, unavailable_groups={"behavior", "trust"})
        score, _accepted = score_signals(sample, DEFAULT_THRESHOLD)
        expected_neutral_loss = (
            GROUP_BUDGETS["behavior"] * 0.5
            + GROUP_BUDGETS["trust"] * 0.5
        )
        self.assertAlmostEqual(score, 20.0 - expected_neutral_loss, places=2)
        self.assertGreater(score, 15.0)

    def test_critical_failure_blocks_auto_verify_even_with_high_score(self):
        sample = signals(passed=True)
        sample[0] = Signal(
            key="critical",
            label="Critical",
            passed=False,
            group="identity",
            weight=0.01,
            critical=True,
        )
        score, accepted = score_signals(sample, 16)
        self.assertGreater(score, 19.0)
        self.assertFalse(accepted)

    def test_wrong_signal_count_fails_closed(self):
        with self.assertRaises(ValueError):
            score_signals(signals()[:-1])
        with self.assertRaises(ValueError):
            score_signals(signals() + [Signal("extra", "Extra", True, "trust")])

    def test_source_contains_exactly_40_runtime_signal_definitions(self):
        source = Path("cogs/automatic_verification_v5.py").read_text(encoding="utf-8")
        collect = source.split("signals = [", 1)[1].split("if len(signals)", 1)[0]
        self.assertEqual(collect.count("Signal("), 40)
        self.assertIn("8 familles pondérées", source)
        self.assertIn("pending_recheck", source)
        self.assertIn("adaptive-followup", source)

    def test_low_score_path_never_bans_or_kicks(self):
        source = Path("cogs/automatic_verification_v5.py").read_text(encoding="utf-8")
        evaluate = source.split("async def evaluate_member", 1)[1].split("def schedule_evaluation", 1)[0]
        low_score = evaluate.split("if not passed:", 1)[1].split("unverified =", 1)[0]
        self.assertNotIn(".ban(", low_score)
        self.assertNotIn(".kick(", low_score)
        self.assertIn('"review"', low_score)

    def test_behavior_keeps_only_fingerprints_not_message_text(self):
        source = Path("cogs/automatic_verification_v5.py").read_text(encoding="utf-8")
        self.assertIn("hashlib.blake2s", source)
        self.assertIn('state["fingerprints"]', source)
        self.assertNotIn("INSERT INTO automatic_verification_events_v4(guild_id,user_id,kind,created_at) VALUES(?,?,?,?)\"\n            , (message", source)

    def test_language_bridge_reapplies_final_ui_cleanup(self):
        source = Path("cogs/control_center_v3_language.py").read_text(encoding="utf-8")
        self.assertIn("automatic_verification_v5.install(bot)", source)
        self.assertIn("install_control_center_v3_ui_fix(bot)", source)


if __name__ == "__main__":
    unittest.main()
