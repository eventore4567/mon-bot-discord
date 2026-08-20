from __future__ import annotations

import unittest

from utils.v22_rules import (
    clean_reason,
    parse_friendly_amount,
    parse_friendly_duration,
    safe_penalty,
    ttl_is_fresh,
)


class V22RulesTests(unittest.TestCase):
    def test_friendly_amounts(self):
        self.assertEqual(parse_friendly_amount("1 500"), 1500)
        self.assertEqual(parse_friendly_amount("1_500"), 1500)
        self.assertEqual(parse_friendly_amount("1.5k"), 1500)
        self.assertEqual(parse_friendly_amount("1.234k"), 1234)
        self.assertEqual(parse_friendly_amount("2m"), 2_000_000)
        self.assertEqual(parse_friendly_amount("tout", 4321), 4321)
        self.assertIsNone(parse_friendly_amount("-10"))
        self.assertIsNone(parse_friendly_amount("999999999999999999999"))

    def test_compound_duration(self):
        self.assertEqual(parse_friendly_duration("10m"), 600)
        self.assertEqual(parse_friendly_duration("1h30m"), 5400)
        self.assertEqual(parse_friendly_duration("2 j 3 h"), 183600)
        self.assertEqual(parse_friendly_duration("1 semaine"), 604800)
        self.assertIsNone(parse_friendly_duration("abc10m"))
        self.assertIsNone(parse_friendly_duration("10"))

    def test_reason_cleanup(self):
        self.assertEqual(clean_reason("   spam     répété   "), "spam répété")
        self.assertEqual(clean_reason(""), "Aucune raison fournie")
        self.assertLessEqual(len(clean_reason("x" * 1000)), 400)

    def test_penalty_never_goes_negative(self):
        self.assertEqual(safe_penalty(20, 100), 20)
        self.assertEqual(safe_penalty(0, 100), 0)
        self.assertEqual(safe_penalty(500, 80), 80)

    def test_ttl(self):
        self.assertTrue(ttl_is_fresh(100.0, 109.9, 10.0))
        self.assertFalse(ttl_is_fresh(100.0, 110.0, 10.0))
        self.assertFalse(ttl_is_fresh(110.0, 109.0, 10.0))


if __name__ == "__main__":
    unittest.main()
