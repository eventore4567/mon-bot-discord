"""core/observability/metrics.py : compteurs et latences en mémoire par commande.

Module additif (Core V2, Phase 1) : jamais appelé pour décider quoi que ce
soit, seulement pour observer. Ces tests vérifient l'agrégation multi-transport,
le calcul de percentile, et l'isolation entre commandes."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from core.observability import metrics


class RecordAndSnapshotTests(unittest.TestCase):
    def setUp(self):
        metrics.reset_for_tests()

    def test_snapshot_vide_sans_donnees(self):
        self.assertEqual(metrics.snapshot(), {})

    def test_compte_les_succes_et_calcule_le_taux(self):
        metrics.record("ban", "slash", 100.0, success=True)
        metrics.record("ban", "slash", 200.0, success=True)
        metrics.record("ban", "slash", 0.0, success=False)

        stats = metrics.snapshot("ban")["ban"]
        self.assertEqual(stats.count, 3)
        self.assertEqual(stats.success_count, 2)
        self.assertEqual(stats.failure_count, 1)
        self.assertAlmostEqual(stats.success_rate, 2 / 3)

    def test_fusionne_prefix_et_slash_sous_la_meme_commande(self):
        metrics.record("play", "prefix", 50.0, success=True)
        metrics.record("play", "slash", 150.0, success=True)

        stats = metrics.snapshot("play")["play"]
        self.assertEqual(stats.count, 2)
        self.assertEqual(stats.success_count, 2)

    def test_commandes_isolees_entre_elles(self):
        metrics.record("ban", "slash", 100.0, success=True)
        metrics.record("kick", "slash", 100.0, success=True)

        snap = metrics.snapshot()
        self.assertEqual(set(snap), {"ban", "kick"})
        self.assertEqual(snap["ban"].count, 1)
        self.assertEqual(snap["kick"].count, 1)

    def test_percentiles_croissants_et_coherents(self):
        for latency in [10, 20, 30, 40, 100]:
            metrics.record("queue", "prefix", float(latency), success=True)

        stats = metrics.snapshot("queue")["queue"]
        self.assertLessEqual(stats.p50_ms, stats.p95_ms)
        self.assertLessEqual(stats.p95_ms, stats.p99_ms)
        self.assertEqual(stats.p99_ms, 100.0)

    def test_record_error_incremente_les_echecs_sans_latence(self):
        metrics.record_error("gamble", "slash")
        stats = metrics.snapshot("gamble")["gamble"]
        self.assertEqual(stats.failure_count, 1)
        self.assertEqual(stats.success_count, 0)
        self.assertEqual(stats.p50_ms, 0.0)

    def test_recent_failures_compte_les_echecs_recents(self):
        metrics.record_error("mute", "prefix")
        metrics.record_error("mute", "prefix")
        stats = metrics.snapshot("mute")["mute"]
        self.assertEqual(stats.recent_failures, 2)

    def test_reset_for_tests_vide_completement(self):
        metrics.record("ban", "slash", 100.0, success=True)
        metrics.reset_for_tests()
        self.assertEqual(metrics.snapshot(), {})


if __name__ == "__main__":
    unittest.main()
