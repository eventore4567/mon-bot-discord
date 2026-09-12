import pytest

from utils.music.providers.spotify import SpotifyProvider, _parse_id


ALAN_WALKER_PLAYLIST_URL = "https://open.spotify.com/playlist/37i9dQZF1DZ06evO4rvWRa"


def _track(track_id: str, title: str) -> dict:
    return {
        "id": track_id,
        "name": title,
        "artists": [{"name": "Alan Walker"}],
        "duration_ms": 180000,
        "external_urls": {"spotify": f"https://open.spotify.com/track/{track_id}"},
        "album": {"name": "Test Album", "images": []},
    }


def test_real_alan_walker_playlist_url_is_recognized():
    assert _parse_id(ALAN_WALKER_PLAYLIST_URL) == (
        "playlist",
        "37i9dQZF1DZ06evO4rvWRa",
    )
    assert SpotifyProvider().matches(ALAN_WALKER_PLAYLIST_URL)


@pytest.mark.asyncio
async def test_spotify_playlist_uses_2026_items_endpoint_and_follows_next_pages(monkeypatch):
    provider = SpotifyProvider()

    async def fake_token(_session):
        return "test-token"

    first = {
        "items": [{"item": _track("a1", "First")}, {"item": _track("a2", "Second")}],
        "next": "https://api.spotify.com/v1/playlists/demo/items?offset=2&limit=100",
    }
    second = {
        "items": [{"item": _track("a3", "Third")}],
        "next": None,
    }
    calls = []

    async def fake_get(_session, url, _headers, *, not_found_query, forbidden_reason=None):
        calls.append((url, not_found_query, forbidden_reason))
        return first if len(calls) == 1 else second

    monkeypatch.setattr(provider, "_get_token", fake_token)
    monkeypatch.setattr(provider, "_api_get", fake_get)

    tracks = await provider._resolve_via_api("playlist", "demo", requested_by=42)

    assert [track.title for track in tracks] == ["First", "Second", "Third"]
    assert len(calls) == 2
    assert calls[0][0] == "https://api.spotify.com/v1/playlists/demo/items?limit=100"
    assert calls[1][0] == first["next"]
    assert "playlist-spotify-2026" in calls[0][2]
    assert all(track.requested_by == 42 for track in tracks)


@pytest.mark.asyncio
async def test_spotify_playlist_keeps_extended_quota_legacy_item_shape_compatible(monkeypatch):
    provider = SpotifyProvider()

    async def fake_token(_session):
        return "test-token"

    page = {
        "items": [{"track": _track("legacy", "Legacy shape")}],
        "next": None,
    }

    async def fake_get(_session, _url, _headers, *, not_found_query, forbidden_reason=None):
        return page

    monkeypatch.setattr(provider, "_get_token", fake_token)
    monkeypatch.setattr(provider, "_api_get", fake_get)

    tracks = await provider._resolve_via_api("playlist", "demo", requested_by=9)
    assert [track.title for track in tracks] == ["Legacy shape"]


@pytest.mark.asyncio
async def test_spotify_playlist_caps_metadata_at_100(monkeypatch):
    provider = SpotifyProvider()

    async def fake_token(_session):
        return "test-token"

    page = {
        "items": [{"item": _track(f"id{i}", f"Track {i}")} for i in range(100)],
        "next": "https://api.spotify.com/v1/playlists/demo/items?offset=100&limit=100",
    }
    calls = 0

    async def fake_get(_session, _url, _headers, *, not_found_query, forbidden_reason=None):
        nonlocal calls
        calls += 1
        return page

    monkeypatch.setattr(provider, "_get_token", fake_token)
    monkeypatch.setattr(provider, "_api_get", fake_get)

    tracks = await provider._resolve_via_api("playlist", "demo", requested_by=7)

    assert len(tracks) == 100
    assert calls == 1
