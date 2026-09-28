from __future__ import annotations

import io

from PIL import Image, ImageDraw

from cogs import utility


def _animated_fixture() -> bytes:
    frames = []
    for x in (0, 8, 16, 24):
        frame = Image.new("RGBA", (48, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(frame)
        draw.rectangle((x, 6, x + 15, 25), fill=(255, 80, 80, 255))
        frames.append(frame)
    out = io.BytesIO()
    frames[0].save(
        out,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=[80, 120, 200, 100],
        loop=0,
        disposal=2,
        optimize=True,
        transparency=0,
    )
    return out.getvalue()


def test_animation_sampling_preserves_total_duration():
    frames = [Image.new("RGBA", (8, 8), (255, 0, 0, 255)) for _ in range(4)]
    sampled, durations = utility._sample_animation(frames, [80, 120, 200, 100], 2)
    assert len(sampled) == 2
    assert durations == [200, 300]
    assert sum(durations) == 500


def test_animated_encoder_keeps_full_nonblank_frames_and_speed():
    raw = _animated_fixture()
    encoded = utility._encode_animated_emoji(raw)
    assert encoded.startswith((b"GIF87a", b"GIF89a"))
    assert len(encoded) <= utility.MAX_EMOJI_BYTES

    with Image.open(io.BytesIO(encoded)) as result:
        assert getattr(result, "n_frames", 1) == 4
        durations = []
        for index in range(result.n_frames):
            result.seek(index)
            durations.append(int(result.info.get("duration", 0) or 0))
            rgba = result.convert("RGBA")
            assert rgba.size == (128, 128)
            assert rgba.getbbox() is not None

    # GIF arrondit les durées à 10 ms ; ce fixture est déjà aligné sur 10 ms.
    assert sum(durations) == 500


def test_partial_delta_frames_are_composited_before_resize():
    raw = _animated_fixture()
    frames, durations, _loop = utility._animated_source_frames(raw, 128)
    assert len(frames) == 4
    assert durations == [80, 120, 200, 100]
    assert all(frame.size == (128, 128) for frame in frames)
    assert all(frame.getbbox() is not None for frame in frames)


def test_direct_discord_copy_prefers_original_gif_before_resized_cdn_variant():
    from pathlib import Path
    source = Path("cogs/emoji_name_lookup.py").read_text(encoding="utf-8")
    original = 'f"https://cdn.discordapp.com/emojis/{emoji_id}.{extension}",'
    resized = 'f"https://cdn.discordapp.com/emojis/{emoji_id}.{extension}?size=128&quality=lossless",'
    assert source.index(original) < source.index(resized)
    assert "Discord n'a pas renvoyé le GIF original" in source
