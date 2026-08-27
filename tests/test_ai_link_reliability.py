import unittest

from cogs.natural_music_intent_guard import (
    _ensure_visible_link_result,
    _looks_like_link_request,
)


class AiLinkReliabilityTests(unittest.TestCase):
    def test_explicit_link_requests_are_detected_without_relationship_false_positive(self):
        self.assertTrue(_looks_like_link_request("SentriX donne moi le lien de la vidéo"))
        self.assertTrue(_looks_like_link_request("tu as le lien du site officiel ?"))
        self.assertFalse(_looks_like_link_request("quel est le lien entre Python et C ?"))

    def test_unverified_youtube_url_is_removed_and_verified_source_is_exposed_raw(self):
        bad = "https://www.youtube.com/watch?v=AAAAAAAAAAA"
        good = "https://www.youtube.com/watch?v=BBBBBBBBBBB"
        text = (
            f"J'ai trouvé cette vidéo : {bad}\n\n"
            f"Sources :\n- [Vidéo officielle]({good})"
        )

        result = _ensure_visible_link_result(text, "donne moi le lien youtube de cette vidéo")

        self.assertNotIn(bad, result)
        self.assertIn(good, result)
        self.assertIn("Liens vérifiés", result)
        self.assertIn("Lien direct vérifié", result)
        self.assertNotIn("[Vidéo officielle](", result)

    def test_video_request_without_cited_url_gets_safe_search_fallback(self):
        result = _ensure_visible_link_result(
            "Je n'ai pas trouvé de lien direct fiable.",
            "SentriX trouve moi la vidéo test sur youtube",
        )

        self.assertIn("https://www.youtube.com/results?search_query=", result)
        self.assertIn("Lien de recherche vérifié", result)

    def test_generic_link_request_always_has_a_clickable_fallback(self):
        result = _ensure_visible_link_result(
            "Je n'ai pas de source directe.",
            "passe moi le lien du site exemple",
        )

        self.assertIn("https://www.google.com/search?q=", result)
        self.assertIn("Lien de recherche", result)


if __name__ == "__main__":
    unittest.main()
