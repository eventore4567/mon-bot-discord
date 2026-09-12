"""cogs/final_error_embed_v5.py — le repli générique appelle désormais
core.errors.pipeline.report() (Core V2, Phase 1). Corrige la lacune vivante
confirmée par l'audit : avant, une exception générique ne laissait aucune
trace journalisée, seulement un compteur anonyme. Voir
docs/core-v2-audit-technical-debt.md §2."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import final_error_embed_v5 as erreurs
from core.errors import pipeline as error_pipeline
from utils import sentrix_panels as panels


class _FauxCtx:
    clean_prefix = "+"
    invoked_with = "test"
    command = SimpleNamespace(qualified_name="ban", signature="<membre>")
    guild = SimpleNamespace(id=999)
    author = SimpleNamespace(id=111)


class PrefixGenericFallbackTests(unittest.TestCase):
    def setUp(self):
        error_pipeline.reset_for_tests()

    def test_le_panneau_contient_une_reference_sxr(self):
        panneau = erreurs._prefix_error_panel(_FauxCtx(), RuntimeError("boum"))
        texte = panels.texte_complet(panneau)
        self.assertIn("SXR-CMD-", texte)

    def test_la_trace_complete_est_journalisee_avec_le_meme_code(self):
        with self.assertLogs("core.errors", level="ERROR") as captured:
            panneau = erreurs._prefix_error_panel(_FauxCtx(), RuntimeError("boum"))
        texte = panels.texte_complet(panneau)

        code_journalise = None
        for record in captured.records:
            if "SXR-CMD-" in record.getMessage():
                code_journalise = record.getMessage().split("code=")[1].split()[0]
        self.assertIsNotNone(code_journalise)
        self.assertIn(code_journalise, texte)

    def test_transporte_le_bon_contexte(self):
        with self.assertLogs("core.errors", level="ERROR") as captured:
            erreurs._prefix_error_panel(_FauxCtx(), RuntimeError("boum"))
        message = captured.records[0].getMessage()
        self.assertIn("command=ban", message)
        self.assertIn("transport=prefix", message)
        self.assertIn("guild=999", message)
        self.assertIn("user=111", message)


class SlashGenericFallbackTests(unittest.TestCase):
    def setUp(self):
        error_pipeline.reset_for_tests()

    def test_le_panneau_contient_une_reference_sxr(self):
        erreur = RuntimeError("boum")
        panneau = erreurs._slash_error_panel(erreur, command="play", guild_id=42, user_id=7)
        texte = panels.texte_complet(panneau)
        self.assertIn("SXR-CMD-", texte)

    def test_reste_retrocompatible_sans_contexte(self):
        """Un appelant existant qui ne passe que `error` doit continuer de fonctionner."""
        panneau = erreurs._slash_error_panel(RuntimeError("boum"))
        texte = panels.texte_complet(panneau)
        self.assertIn("SXR-CMD-", texte)

    def test_transporte_le_bon_contexte(self):
        with self.assertLogs("core.errors", level="ERROR") as captured:
            erreurs._slash_error_panel(RuntimeError("boum"), command="play", guild_id=42, user_id=7)
        message = captured.records[0].getMessage()
        self.assertIn("command=play", message)
        self.assertIn("transport=slash", message)
        self.assertIn("guild=42", message)
        self.assertIn("user=7", message)


if __name__ == "__main__":
    unittest.main()
