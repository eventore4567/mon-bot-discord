from cogs.natural_music_intent_guard import (
    _ensure_visible_link_result,
    _looks_like_link_request,
)


def test_explicit_link_requests_are_detected_without_relationship_false_positive():
    assert _looks_like_link_request("SentriX donne moi le lien de la vidéo") is True
    assert _looks_like_link_request("tu as le lien du site officiel ?") is True
    assert _looks_like_link_request("quel est le lien entre Python et C ?") is False


def test_unverified_youtube_url_is_removed_and_verified_source_is_exposed_raw():
    bad = "https://www.youtube.com/watch?v=AAAAAAAAAAA"
    good = "https://www.youtube.com/watch?v=BBBBBBBBBBB"
    text = (
        f"J'ai trouvé cette vidéo : {bad}\n\n"
        f"Sources :\n- [Vidéo officielle]({good})"
    )

    result = _ensure_visible_link_result(text, "donne moi le lien youtube de cette vidéo")

    assert bad not in result
    assert good in result
    assert "Liens vérifiés" in result
    assert "Lien direct vérifié" in result
    assert "[Vidéo officielle](" not in result


def test_video_request_without_cited_url_gets_safe_search_fallback():
    result = _ensure_visible_link_result(
        "Je n'ai pas trouvé de lien direct fiable.",
        "SentriX trouve moi la vidéo test sur youtube",
    )

    assert "https://www.youtube.com/results?search_query=" in result
    assert "Lien de recherche vérifié" in result


def test_generic_link_request_always_has_a_clickable_fallback():
    result = _ensure_visible_link_result(
        "Je n'ai pas de source directe.",
        "passe moi le lien du site exemple",
    )

    assert "https://www.google.com/search?q=" in result
    assert "Lien de recherche" in result
