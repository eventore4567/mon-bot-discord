import json

import sentrix_music_playlists_v108 as playlists


def test_personal_playlist_accepts_up_to_1000_tracks():
    payload = [{"title": f"Track {index}"} for index in range(1001)]

    decoded = playlists.decode_playlist_items(json.dumps(payload))

    assert len(decoded) == 1000
    assert decoded[0]["title"] == "Track 0"
    assert decoded[-1]["title"] == "Track 999"


def test_personal_playlist_limit_constant_is_1000():
    assert playlists._MAX_TRACKS == 1000
