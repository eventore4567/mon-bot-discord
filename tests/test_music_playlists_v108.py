import json

import pytest

from sentrix_music_playlists_v108 import (
    _item_to_track,
    _track_to_item,
    decode_playlist_items,
    normalize_playlist_name,
)
from utils.music import Track


def test_playlist_name_is_normalized_case_insensitively():
    display, key = normalize_playlist_name("  Ma   Playlist  ")
    assert display == "Ma Playlist"
    assert key == "ma playlist"


def test_playlist_name_rejects_empty_and_too_long():
    with pytest.raises(ValueError):
        normalize_playlist_name("   ")
    with pytest.raises(ValueError):
        normalize_playlist_name("x" * 41)


def test_decode_playlist_items_is_defensive_and_bounded():
    assert decode_playlist_items("not-json") == []
    raw = json.dumps([{"title": f"t{i}"} for i in range(150)])
    items = decode_playlist_items(raw)
    assert len(items) == 100
    assert items[0]["title"] == "t0"
    assert items[-1]["title"] == "t99"


def test_track_roundtrip_keeps_refresh_metadata_and_rebinds_requester():
    track = Track(
        title="Song",
        artist="Artist",
        album="Album",
        duration=180,
        thumbnail="https://example.test/cover.jpg",
        original_url="https://soundcloud.com/example/song",
        provider="spotify",
        playable_url="https://expired.example/audio",
        playback_provider="soundcloud",
        requested_by=1,
    )
    item = _track_to_item(track, "Artist Song")
    restored = _item_to_track(item, requested_by=999)

    assert restored.title == "Song"
    assert restored.artist == "Artist"
    assert restored.original_url == "https://soundcloud.com/example/song"
    assert restored.playback_provider == "soundcloud"
    assert restored.playable_url is None
    assert restored.requested_by == 999
