import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from sentrix_music_playlists_v108 import (
    _install_finish_ping,
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
    raw = json.dumps([{"title": f"t{i}"} for i in range(1001)])
    items = decode_playlist_items(raw)
    assert len(items) == 1000
    assert items[0]["title"] == "t0"
    assert items[-1]["title"] == "t999"


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



@pytest.mark.asyncio
async def test_finish_ping_wrapper_forwards_phase6_callback_metadata():
    class FakeMusicCog:
        def __init__(self):
            self.calls = []
            self._sentrix_finish_ping_v108 = False

        async def _on_track_finished(
            self,
            queue,
            *,
            error=None,
            generation=None,
            finished_track=None,
        ):
            self.calls.append(
                {
                    "error": error,
                    "generation": generation,
                    "finished_track": finished_track,
                }
            )
            queue.current = None

    cog = FakeMusicCog()
    _install_finish_ping(cog)

    requester = 4242
    track = Track(title="Song", artist="Artist", requested_by=requester)
    channel = SimpleNamespace(send=AsyncMock())
    queue = SimpleNamespace(
        current=track,
        text_channel=channel,
        guild_id=123,
    )
    error = RuntimeError("ffmpeg ended")

    await cog._on_track_finished(
        queue,
        error=error,
        generation=7,
        finished_track=track,
    )

    assert len(cog.calls) == 1
    assert cog.calls[0]["error"] is error
    assert cog.calls[0]["generation"] == 7
    assert cog.calls[0]["finished_track"] is track
    assert channel.send.await_count == 1
    assert f"<@{requester}>" in channel.send.await_args.args[0]


@pytest.mark.asyncio
async def test_finish_ping_wrapper_does_not_ping_stale_manual_stop_callback():
    class FakeMusicCog:
        def __init__(self):
            self._sentrix_finish_ping_v108 = False

        async def _on_track_finished(
            self,
            queue,
            *,
            error=None,
            generation=None,
            finished_track=None,
        ):
            # Le vrai moteur phase 6 ignore ici un callback de génération obsolète.
            return

    cog = FakeMusicCog()
    _install_finish_ping(cog)

    stopped_track = Track(title="Stopped", requested_by=777)
    channel = SimpleNamespace(send=AsyncMock())
    queue = SimpleNamespace(
        current=None,
        text_channel=channel,
        guild_id=321,
    )

    await cog._on_track_finished(
        queue,
        generation=1,
        finished_track=stopped_track,
    )

    channel.send.assert_not_awaited()
