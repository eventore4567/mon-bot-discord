from sentrix_music_playlist_semantics import _valid_external_url
from sentrix_music_product_errors import _classify
from utils.music import NoPlayableSource, ProviderUnavailable, TrackNotFound


def test_playlist_import_accepts_supported_providers_only():
    assert _valid_external_url("https://open.spotify.com/playlist/abc")
    assert _valid_external_url("https://www.youtube.com/playlist?list=abc")
    assert _valid_external_url("https://soundcloud.com/user/sets/list")
    assert _valid_external_url("https://www.deezer.com/playlist/123")
    assert not _valid_external_url("https://example.com/open.spotify.com/playlist/abc")
    assert not _valid_external_url("javascript:alert(1)")


def test_missing_spotify_credentials_get_a_precise_message():
    title, description = _classify(
        ProviderUnavailable(
            "spotify",
            "SPOTIFY_CLIENT_ID/SPOTIFY_CLIENT_SECRET requis pour importer un album ou une playlist Spotify",
        )
    )
    assert title == "Spotify non configuré"
    assert "Railway" in description


def test_unavailable_provider_is_not_reported_as_track_missing():
    title, _ = _classify(ProviderUnavailable("youtube", "API HTTP 429"))
    assert "limité" in title

    title, _ = _classify(TrackNotFound("spotify", "abc"))
    assert title == "Titre introuvable"

    title, description = _classify(NoPlayableSource("Faded", ["youtube", "soundcloud"]))
    assert title == "Aucune source audio disponible"
    assert "youtube" in description
