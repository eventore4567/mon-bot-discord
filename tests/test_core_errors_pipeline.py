"""core/errors/pipeline.py : génération de référence + journalisation de trace.

Corrige une lacune vivante trouvée par l'audit Core V2 (docs/core-v2-audit-
technical-debt.md, §2) : le gestionnaire d'erreur réellement actif aujourd'hui
n'écrivait aucune trace pour une exception générique. Ces tests vérifient le
comportement observable requis : un code stable et unique par appel, un
message utilisateur qui ne fuite jamais le texte de l'exception, et une trace
complète effectivement journalisée."""
from __future__ import annotations

import logging
import os
import unittest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from core.errors import pipeline


class NextCodeTests(unittest.TestCase):
    def setUp(self):
        pipeline.reset_for_tests()

    def test_codes_sont_uniques_et_croissants(self):
        first = pipeline.next_code()
        second = pipeline.next_code()
        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("SXR-CMD-"))
        self.assertTrue(second.startswith("SXR-CMD-"))

    def test_format_a_quatre_chiffres_minimum(self):
        code = pipeline.next_code()
        digits = code.rsplit("-", 1)[-1]
        self.assertEqual(len(digits), 4)
        self.assertTrue(digits.isdigit())


class ReportTests(unittest.TestCase):
    def setUp(self):
        pipeline.reset_for_tests()

    def test_message_utilisateur_ne_contient_jamais_le_texte_de_l_exception(self):
        exc = ValueError("mot de passe secret dans le message d'exception")
        entry = pipeline.report(exc, command="ban", transport="slash")
        message = entry.user_message()
        self.assertNotIn("mot de passe secret", message)
        self.assertIn(entry.code, message)
        self.assertIn("Référence", message)

    def test_clean_message_est_identique_a_user_message(self):
        exc = RuntimeError("peu importe")
        entry = pipeline.report(exc, command="play", transport="prefix")
        self.assertEqual(pipeline.clean_message(entry), entry.user_message())

    def test_capture_le_contexte_de_la_commande(self):
        exc = KeyError("guild_id")
        entry = pipeline.report(
            exc,
            command="music play",
            transport="slash",
            guild_id=123,
            user_id=456,
            stage="resolve_metadata",
        )
        self.assertEqual(entry.command, "music play")
        self.assertEqual(entry.transport, "slash")
        self.assertEqual(entry.guild_id, 123)
        self.assertEqual(entry.user_id, 456)
        self.assertEqual(entry.stage, "resolve_metadata")
        self.assertEqual(entry.exc_type, "KeyError")

    def test_journalise_la_trace_complete_avec_le_meme_code(self):
        """C'est exactement le bug corrigé : avant, rien n'était journalisé."""
        exc = ValueError("boum")
        with self.assertLogs("core.errors", level="ERROR") as captured:
            entry = pipeline.report(exc, command="ban", transport="slash")

        self.assertEqual(len(captured.records), 1)
        record = captured.records[0]
        self.assertIn(entry.code, record.getMessage())
        self.assertIsNotNone(record.exc_info)
        self.assertIs(record.exc_info[1], exc)

    def test_message_exception_tronque_a_500_caracteres(self):
        exc = ValueError("x" * 2000)
        entry = pipeline.report(exc, command="ban", transport="prefix")
        self.assertLessEqual(len(entry.exc_message), 500)


if __name__ == "__main__":
    unittest.main()
