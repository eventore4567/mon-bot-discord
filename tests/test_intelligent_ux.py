from __future__ import annotations

import unittest

from utils.intelligent_ux import canonical_amount, classify_ticket_priority, parse_natural_action, summarize_ticket


class IntelligentUXTests(unittest.TestCase):
    def test_safe_actions(self):
        self.assertEqual(parse_natural_action("ouvre mon profil").command, "profile")
        self.assertEqual(parse_natural_action("montre mon solde").command, "balance")
        self.assertEqual(parse_natural_action("je veux travailler").command, "work")
        self.assertFalse(parse_natural_action("ouvre mon profil").sensitive)

    def test_payment_requires_confirmation(self):
        plan = parse_natural_action("envoie 1.5k à <@123456789>")
        self.assertIsNotNone(plan)
        self.assertEqual(plan.command, "pay")
        self.assertEqual(plan.amount, "1500")
        self.assertEqual(plan.reason, "Aucune raison fournie")
        self.assertTrue(plan.sensitive)
        self.assertTrue(plan.target_required)

    def test_k_amount_is_canonical_for_legacy_pay(self):
        plan = parse_natural_action("envoie 5k à <@123456789>")
        self.assertIsNotNone(plan)
        self.assertEqual(plan.amount, "5000")
        self.assertEqual(plan.reason, "Aucune raison fournie")
        self.assertEqual(canonical_amount("2m"), "2000000")
        self.assertEqual(canonical_amount("1,5k"), "1500")

    def test_payment_reason_remains_meaningful(self):
        plan = parse_natural_action("envoie 5k à <@123456789> remboursement concours")
        self.assertEqual(plan.amount, "5000")
        self.assertIn("remboursement", plan.reason.casefold())
        self.assertNotEqual(plan.reason.strip().casefold(), "à")

    def test_moderation_is_never_automatic(self):
        plan = parse_natural_action("mute <@123456789> 30m spam répété")
        self.assertEqual(plan.command, "mute")
        self.assertEqual(plan.duration, "30m")
        self.assertTrue(plan.sensitive)
        self.assertIn("spam", plan.reason.casefold())

        ban = parse_natural_action("ban <@123456789> raid")
        self.assertEqual(ban.command, "ban")
        self.assertTrue(ban.sensitive)

    def test_tempban_without_duration_is_not_planned(self):
        self.assertIsNone(parse_natural_action("ban temporaire <@123456789>"))

    def test_questions_are_not_hijacked(self):
        self.assertIsNone(parse_natural_action("comment gagner de l'argent rapidement ?"))
        self.assertIsNone(parse_natural_action("explique moi comment fonctionne la modération"))
        self.assertIsNone(parse_natural_action("donne moi 5 idées de jeux"))

    def test_ticket_priority(self):
        self.assertEqual(classify_ticket_priority("mon compte a été hacké urgence")[1], "Haute")
        self.assertEqual(classify_ticket_priority("je subis du harcèlement")[1], "Élevée")
        self.assertEqual(classify_ticket_priority("bonjour j'ai une question")[1], "Normale")

    def test_ticket_summary_is_bounded(self):
        value = summarize_ticket("Support", [("Problème", "Je ne peux pas me connecter")])
        self.assertIn("Support", value)
        self.assertIn("connecter", value)
        self.assertLessEqual(len(value), 420)


if __name__ == "__main__":
    unittest.main()
