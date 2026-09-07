import io

from PIL import Image, ImageDraw

from cogs.emoji_name_lookup import _encode_animated_emoji_safe


def _animated_delta_gif() -> bytes:
    """GIF optimise dont les frames suivantes ne stockent que les zones modifiees."""
    frames = []
    canvas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    for index in range(8):
        frame = canvas.copy()
        draw = ImageDraw.Draw(frame)
        x = 8 + index * 12
        draw.rectangle((x, 48, x + 9, 57), fill=(255, 112, 32, 255))
        canvas = frame
        frames.append(frame)

    output = io.BytesIO()
    frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=80,
        loop=0,
        disposal=1,
        transparency=0,
        optimize=True,
    )
    return output.getvalue()


def test_reencoded_gif_keeps_full_frames_and_transparency():
    repaired = _encode_animated_emoji_safe(_animated_delta_gif())

    assert repaired.startswith((b"GIF87a", b"GIF89a"))
    assert len(repaired) <= 256 * 1024

    with Image.open(io.BytesIO(repaired)) as image:
        assert image.n_frames == 8

        image.seek(0)
        first = image.convert("RGBA")
        first_bbox = first.getbbox()
        assert first.getpixel((0, 0))[3] == 0
        assert first_bbox is not None

        image.seek(7)
        last = image.convert("RGBA")
        last_bbox = last.getbbox()
        assert last.getpixel((0, 0))[3] == 0
        assert last_bbox is not None

        # Le dernier etat doit encore contenir les pixels des frames precedentes.
        # Si seules les zones delta avaient ete encodees, la largeur serait proche
        # de celle d'un unique petit rectangle.
        assert last_bbox[2] - last_bbox[0] > first_bbox[2] - first_bbox[0] + 50


def test_reencoded_gif_remains_animated():
    repaired = _encode_animated_emoji_safe(_animated_delta_gif())
    with Image.open(io.BytesIO(repaired)) as image:
        assert getattr(image, "is_animated", False) is True
        assert image.n_frames > 1
