"""Le matching intelligent (utils/music/matcher.py) ne doit jamais prendre le
premier résultat au hasard — c'est la demande explicite qui a motivé la refonte
complète du moteur musique. Ces tests vérifient : normalisation, détection de
variantes (nightcore/slowed/cover/remix/karaoke), score de durée, et le
comportement de pick_best sur des cas réels."""
from __future__ import annotations

import unittest

from utils.music import matcher
from utils.music.models import Track


class NormalizeTests(unittest.TestCase):
    def test_accents_et_ponctuation_ignores(self):
        self.assertEqual(matcher.normalize("Requiém, for a Dream!"), "requiem for a dream")

    def test_espaces_compactes(self):
        self.assertEqual(matcher.normalize("  Toto   Africa  "), "toto africa")


class VariantDetectionTests(unittest.TestCase):
    def test_detecte_nightcore(self):
        self.assertIn("nightcore", matcher.detect_variants("Song Title (Nightcore Version)"))

    def test_detecte_slowed_reverb(self):
        self.assertIn("slowed", matcher.detect_variants("song - slowed + reverb"))

    def test_detecte_cover(self):
        self.assertIn("cover", matcher.detect_variants("Toto - Africa (Cover by Someone)"))

    def test_ne_detecte_rien_sur_un_titre_normal(self):
        self.assertEqual(matcher.detect_variants("Toto - Africa (Official Video)"), set())

    def test_detecte_karaoke_instrumental(self):
        self.assertIn("karaoke", matcher.detect_variants("Africa - Karaoke Instrumental"))


class OfficialDetectionTests(unittest.TestCase):
    def test_reconnait_official_video(self):
        self.assertTrue(matcher.is_official("Toto - Africa (Official Video)"))

    def test_ne_reconnait_pas_un_titre_quelconque(self):
        self.assertFalse(matcher.is_official("Toto - Africa (Lyrics)"))


class PickBestTests(unittest.TestCase):
    def _target(self, title="Africa", artist="Toto", duration=295) -> Track:
        return Track(title=title, artist=artist, duration=duration)

    def test_choisit_la_version_officielle_plutot_qu_un_remix(self):
        target = self._target()
        official = Track(title="Toto - Africa (Official Video)", artist="Toto Vevo", duration=295, playable_url="a")
        remix = Track(title="Toto - Africa (Remix)", artist="DJ Someone", duration=310, playable_url="b")
        best = matcher.pick_best(target, [remix, official], original_query="africa toto")
        self.assertIs(best, official)

    def test_rejette_un_candidat_sans_rapport(self):
        target = self._target()
        unrelated = Track(title="Never Gonna Give You Up", artist="Rick Astley", duration=213, playable_url="a")
        best = matcher.pick_best(target, [unrelated], original_query="africa toto")
        self.assertIsNone(best)

    def test_accepte_un_remix_si_explicitement_demande(self):
        """C'est la nuance demandée : nightcore/slowed/remix/cover/karaoke sont
        écartés PAR DÉFAUT, mais pas si l'utilisateur les a demandés lui-même."""
        target = Track(title="Africa Remix", artist="Toto", duration=None)
        remix = Track(title="Toto - Africa (Remix)", artist="DJ Someone", duration=310, playable_url="a")
        plain = Track(title="Toto - Africa (Official Video)", artist="Toto", duration=295, playable_url="b")
        best = matcher.pick_best(target, [remix, plain], original_query="africa toto remix")
        self.assertIs(best, remix)

    def test_penalise_fortement_un_ecart_de_duree_important(self):
        target = self._target(duration=180)
        wrong_duration = Track(title="Toto - Africa (Official Video)", artist="Toto", duration=3600, playable_url="a")
        best = matcher.pick_best(target, [wrong_duration], original_query="africa toto")
        self.assertIsNone(best)

    def test_liste_vide_ne_plante_pas(self):
        self.assertIsNone(matcher.pick_best(self._target(), [], original_query="africa"))

    def test_duree_inconnue_ne_penalise_pas(self):
        target = Track(title="Africa", artist="Toto", duration=None)
        candidate = Track(title="Toto - Africa (Official Video)", artist="Toto", duration=None, playable_url="a")
        best = matcher.pick_best(target, [candidate], original_query="africa toto")
        self.assertIs(best, candidate)


if __name__ == "__main__":
    unittest.main()
