from __future__ import annotations


def test_ffmpeg_music_defaults_enable_jitter_smoothing():
    import cogs.music as music_module
    from sentrix_music_providers_v102 import _install_smooth_ffmpeg_defaults

    class DummyMusic:
        pass

    # Le patch retrouve le module du vrai Cog via __module__.
    DummyMusic.__module__ = "cogs.music"
    dummy = DummyMusic()
    original = dict(music_module.FFMPEG_OPTIONS)
    try:
        _install_smooth_ffmpeg_defaults(dummy)
        before = music_module.FFMPEG_OPTIONS["before_options"]
        options = music_module.FFMPEG_OPTIONS["options"]

        assert "-reconnect 1" in before
        assert "-reconnect_streamed 1" in before
        assert "-reconnect_at_eof 1" in before
        assert "-reconnect_delay_max 10" in before
        assert "-rw_timeout 15000000" in before
        assert "-ar 48000" in options
        assert "-ac 2" in options
        assert "aresample=48000:async=1000:first_pts=0" in options
        assert "nobuffer" not in before.casefold()
        assert "nobuffer" not in options.casefold()
        assert getattr(dummy, "_sentrix_music_audio_v103", False) is True
    finally:
        music_module.FFMPEG_OPTIONS = original


def test_soundcloud_prefers_progressive_http_over_hls():
    from utils.music.providers.soundcloud import _select_playable_url

    entry = {
        "url": "https://fallback.example/audio.m3u8",
        "formats": [
            {
                "url": "https://cdn.example/high.m3u8",
                "protocol": "m3u8_native",
                "vcodec": "none",
                "abr": 256,
            },
            {
                "url": "https://cdn.example/stable-128.mp3",
                "protocol": "https",
                "vcodec": "none",
                "abr": 128,
            },
            {
                "url": "https://cdn.example/stable-192.mp3",
                "protocol": "https",
                "vcodec": "none",
                "abr": 192,
            },
        ],
    }

    assert _select_playable_url(entry) == "https://cdn.example/stable-192.mp3"


def test_soundcloud_keeps_hls_as_legal_fallback():
    from utils.music.providers.soundcloud import _select_playable_url

    entry = {
        "formats": [
            {
                "url": "https://cdn.example/64.m3u8",
                "protocol": "m3u8_native",
                "vcodec": "none",
                "abr": 64,
            },
            {
                "url": "https://cdn.example/128.m3u8",
                "protocol": "m3u8_native",
                "vcodec": "none",
                "abr": 128,
            },
        ]
    }

    assert _select_playable_url(entry) == "https://cdn.example/128.m3u8"


def test_soundcloud_falls_back_to_ytdlp_selected_url_without_formats():
    from utils.music.providers.soundcloud import _select_playable_url

    assert _select_playable_url({"url": "https://cdn.example/audio.mp3"}) == "https://cdn.example/audio.mp3"
    assert _select_playable_url({}) is None
