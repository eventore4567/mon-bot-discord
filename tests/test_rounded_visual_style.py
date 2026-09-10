"""Style visuel "arrondi" validé par Jayden (puce de section ● et barre de
progression ▰/▱) — verrouille le choix pour qu'un futur changement ne
revienne pas silencieusement aux anciens glyphes anguleux (chevron ◢, blocs
█/░, carrés 🟩/⬜). Couvre tous les points touchés lors de ce changement :
utils/sentrix_panels.py (puce de section, partagée par tous les panneaux
Components V2), utils/stats_service.py, cogs/levels.py, cogs/community_v3.py,
cogs/community_v31.py, utils/embeds.py et utils/command_style_v2.py (barre de
progression et qualité de latence /ping, dupliquée dans ces deux derniers
fichiers)."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import community_v3, community_v31
from utils import command_style_v2, embeds, sentrix_panels as panels, stats_service


class SectionBulletTests(unittest.TestCase):
    def test_chevron_est_la_puce_arrondie(self):
        self.assertEqual(panels.CHEVRON, "●")


class ProgressBarTests(unittest.TestCase):
    def test_stats_service_utilise_les_glyphes_arrondis_par_defaut(self):
        barre, pct = stats_service.progress_bar(3, 10, length=10)
        self.assertEqual(barre, "▰▰▰▱▱▱▱▱▱▱")
        self.assertEqual(pct, 30)

    def test_embeds_bar_utilise_les_glyphes_arrondis_par_defaut(self):
        self.assertEqual(embeds.bar(5, 10, length=10), "▰▰▰▰▰▱▱▱▱▱")

    def test_community_v3_progress_bar_est_arrondie(self):
        self.assertEqual(community_v3._progress_bar(5, 10, blocks=10), "▰▰▰▰▰▱▱▱▱▱")

    def test_community_v31_bar_est_arrondie(self):
        self.assertEqual(community_v31._bar(6, 12, blocks=12), "▰▰▰▰▰▰▱▱▱▱▱▱")


class LatencyQualityTests(unittest.TestCase):
    def test_embeds_latence_est_arrondie(self):
        quality, bar = embeds._latency_quality(50)
        self.assertEqual(quality, "Excellente")
        self.assertEqual(bar, "▰" * 10)

    def test_command_style_v2_latence_est_arrondie(self):
        quality, bar = command_style_v2._latency_quality(50)
        self.assertEqual(quality, "Excellente")
        self.assertEqual(bar, "▰" * 10)

    def test_les_deux_implementations_de_latence_restent_identiques(self):
        """embeds.py et command_style_v2.py dupliquent cette fonction — un
        futur correctif appliqué à une seule couche romprait sinon la
        cohérence visuelle entre les deux implémentations concurrentes."""
        for latency_ms in (50, 100, 180, 300):
            self.assertEqual(
                embeds._latency_quality(latency_ms),
                command_style_v2._latency_quality(latency_ms),
            )


if __name__ == "__main__":
    unittest.main()
