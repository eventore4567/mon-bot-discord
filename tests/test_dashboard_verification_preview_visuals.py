from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_verification_preview_uses_discord_blurple_not_error_red():
    source = _read("web/dashboard_ui/js/30_modules.js")
    start = source.index("async function renderVerification()")
    end = source.index("async function renderSanctions()", start)
    block = source[start:end]
    assert "color: '#5865f2'" in block
    assert "color: '#ff" not in block.lower()


def test_dashboard_preview_renders_static_and_animated_custom_emojis():
    source = _read("web/dashboard_ui/js/00_core.js")
    assert "function renderDiscordCustomEmojis" in source
    assert "cdn.discordapp.com/emojis/" in source
    assert "animated ? 'gif' : 'webp'" in source
    assert "return renderDiscordCustomEmojis(html);" in source


def test_dashboard_preview_has_color_emoji_font_and_inline_custom_emoji_style():
    css = _read("web/dashboard_ui/app.css")
    assert '"Apple Color Emoji"' in css
    assert '"Segoe UI Emoji"' in css
    assert '"Noto Color Emoji"' in css
    assert ".discord-preview .d-custom-emoji" in css
    assert "vertical-align:-.28em" in css


def test_verification_backend_publishes_blurple_embed_too():
    source = _read("web/dashboard_verification_v6.py")
    assert "discord.Colour.blurple()" in source
