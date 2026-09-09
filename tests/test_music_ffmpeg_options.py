from pathlib import Path


def test_music_ffmpeg_reconnect_options_are_supported():
    source = Path("cogs/music.py").read_text(encoding="utf-8")

    # Regression: Railway FFmpeg exited immediately with code 8 because
    # `-reconnect_streamretries` is not a valid FFmpeg HTTP option.
    assert "-reconnect_streamretries" not in source
    assert "-reconnect 1" in source
    assert "-reconnect_streamed 1" in source
    assert "-reconnect_delay_max 5" in source
