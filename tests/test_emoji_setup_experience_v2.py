from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from cogs import emoji_unicode_asset_fix as emoji_fix

ROOT = Path(__file__).resolve().parents[1]


def test_crown_unicode_request_uses_stable_discord_name():
    assert emoji_fix._twemoji_codepoints("👑") == "1f451"
    assert emoji_fix._unicode_request("👑", None) == ("👑", "emoji_1f451")


def test_named_unicode_request_keeps_requested_name():
    assert emoji_fix._unicode_request("couronne", "👑") == ("👑", "couronne")


def test_custom_discord_emoji_is_not_intercepted():
    assert emoji_fix._unicode_request("<:couronne:123456789012345678>", None) is None


def test_safe_png_is_real_static_png_and_small_enough():
    source = Image.new("RGBA", (72, 72), (255, 200, 0, 255))
    raw = io.BytesIO()
    source.save(raw, format="PNG")
    encoded = emoji_fix._safe_static_png(raw.getvalue())
    assert encoded.startswith(emoji_fix.PNG_SIGNATURE)
    assert len(encoded) <= emoji_fix.MAX_EMOJI_BYTES
    with Image.open(io.BytesIO(encoded)) as check:
        assert check.format == "PNG"
        assert check.size == (emoji_fix.EMOJI_SIZE, emoji_fix.EMOJI_SIZE)
        assert getattr(check, "n_frames", 1) == 1


def test_runtime_load_order_keeps_wrappers_safe():
    boot = (ROOT / "railway_boot.py").read_text(encoding="utf-8")
    assert boot.index('bot_main.EXTENSIONS.append("cogs.setup_auto_fix")') < boot.index(
        'bot_main.EXTENSIONS.append("cogs.setup_experience_v2")'
    )
    assert boot.index('bot_main.EXTENSIONS.append("cogs.emoji_name_lookup")') < boot.index(
        'bot_main.EXTENSIONS.append("cogs.emoji_unicode_asset_fix")'
    )


def test_setup_upgrade_remains_additive_and_confirmed():
    source = (ROOT / "cogs" / "setup_experience_v2.py").read_text(encoding="utf-8")
    assert "original_home_embed = SetupView._build_home_embed" in source
    assert "original_build_embed = SetupView.build_embed" in source
    assert "original_render_home = SetupView._render_home" in source
    assert "AutoSetupConfirmView" in source
    assert 'label="Diagnostic"' in source
    assert 'label="Actualiser"' in source
    assert "platform.quick_setup" in source
    assert "await _can_use_setup" in source
