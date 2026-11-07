"""Compact Components V2 presentation for published ticket panels.

This module only renders saved settings; it never overwrites server configuration.
The 4-pixel banner is generated from stdlib PNG bytes (no third-party image assets).
"""

import io
import struct
import zlib

import discord


_DEFAULT_DESCRIPTIONS = {
    "Choisissez une option ci-dessous pour ouvrir un ticket.",
    "Choisissez une catégorie pour ouvrir un ticket.",
}


def _chunk(tag: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + tag + body + struct.pack(
        ">I", zlib.crc32(tag + body) & 0xFFFFFFFF
    )


def thin_banner_png(color: int, width: int = 960, height: int = 4) -> bytes:
    """Tiny valid PNG, wide enough for a very thin Discord media strip."""
    color = int(color) & 0xFFFFFF
    rgb = bytes(((color >> 16) & 255, (color >> 8) & 255, color & 255))
    raw = (b"\x00" + rgb * width) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


class SlimTicketPanel(discord.ui.LayoutView):
    """A slim, single-message, persistent Components V2 ticket panel."""

    def __init__(self, panel):
        super().__init__(timeout=None)
        color = int(panel["color"] or 0x7658E8) & 0xFFFFFF
        self._banner_enabled = bool(panel["banner_enabled"])
        self._color = color

        container = discord.ui.Container(accent_colour=discord.Colour(color))
        if self._banner_enabled:
            banner = discord.ui.MediaGallery()
            banner.add_item(media="attachment://sentrix-ticket-strip.png")
            container.add_item(banner)

        title = (panel["title"] or "").strip()
        if not title or title in {"🎫 Support", "🎫 Tickets", "🎟️ Tickets"}:
            title = "Centre de tickets"
        description = (panel["description"] or "").strip()
        if not description or description in _DEFAULT_DESCRIPTIONS:
            description = "Choisissez une catégorie pour contacter notre équipe."

        header = discord.ui.TextDisplay(f"## {title}\n{description}")
        thumbnail_url = (panel["thumbnail_url"] or "").strip()
        if thumbnail_url:
            try:
                container.add_item(
                    discord.ui.Section(header, accessory=discord.ui.Thumbnail(thumbnail_url))
                )
            except (ValueError, TypeError):
                container.add_item(header)
        else:
            container.add_item(header)

        image_url = (panel["image_url"] or "").strip()
        if image_url:
            gallery = discord.ui.MediaGallery()
            gallery.add_item(media=image_url)
            container.add_item(gallery)

        footer = (panel["footer_text"] or "").strip()
        if footer:
            container.add_item(discord.ui.TextDisplay(f"-# {footer}"))

        self.add_item(container)

    def fichiers(self) -> list[discord.File]:
        if not self._banner_enabled:
            return []
        return [
            discord.File(
                io.BytesIO(thin_banner_png(self._color)),
                filename="sentrix-ticket-strip.png",
            )
        ]
