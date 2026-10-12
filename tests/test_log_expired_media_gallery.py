"""Regression: expired Discord deleted-message images must never make 2x2 broken galleries."""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
import pytest

from cogs.logs import _attachment_media, _snapshot_deleted_images
from utils import wide_logs


def _components(view, typ):
    found = []
    def walk(items):
        for item in items:
            if isinstance(item, typ):
                found.append(item)
            walk(getattr(item, "children", ()) or ())
    walk(view.children)
    return found


def _text(view):
    return "\n".join(x.content for x in _components(view, discord.ui.TextDisplay))


def _embed():
    embed = discord.Embed(title="Message supprimé", description="Quatre images jointes")
    embed.set_footer(text="SentriX")
    return embed


def _attachments(count: int, *, readable: bool = True):
    attachments = []
    for index in range(count):
        att = SimpleNamespace(
            url=f"https://cdn.discordapp.com/attachments/123/456/source-{index}.png?ex=expired",
            filename=f"source-{index}.png",
            content_type="image/png",
            size=5,
            read=AsyncMock(return_value=b"\x89PNG\r\n\x1a\n" + bytes([index])),
        )
        if not readable:
            att.read.side_effect = discord.NotFound(
                SimpleNamespace(status=404, reason="Not Found"),
                "Unknown Attachment",
            )
        attachments.append(att)
    return attachments


def test_four_expired_cdn_urls_are_links_not_four_broken_images():
    media = _attachment_media(_attachments(4))
    view = wide_logs.WideLogView(_embed(), "", log_type="message_delete", media_items=media)
    assert not _components(view, discord.ui.MediaGallery)
    text = _text(view)
    assert text.count("Aperçu non conservé") == 4
    assert text.count("Ouvrir source-") == 4


@pytest.mark.asyncio
async def test_four_recovered_images_are_copied_into_message_gallery():
    original = _attachments(4)
    media, uploads = await _snapshot_deleted_images(original, _attachment_media(original))
    assert len(uploads) == 4
    assert all(source.startswith("attachment://sentrix-log-image-") for source, _, _ in media)
    assert all(attachment.read.await_count == 1 for attachment in original)
    view = wide_logs.WideLogView(
        _embed(), "", log_type="message_delete",
        media_items=media,
        available_attachments={upload.filename for upload in uploads},
    )
    galleries = _components(view, discord.ui.MediaGallery)
    assert len(galleries) == 1
    assert len(galleries[0].items) == 4
    for file in uploads:
        file.close()


@pytest.mark.asyncio
async def test_deleted_unavailable_images_do_not_create_missing_attachments():
    images = _attachments(4)
    for att in images:
        att.read.side_effect = OSError("Discord CDN link expired")
    originals = _attachment_media(images)
    media, files = await _snapshot_deleted_images(images, originals)
    assert media == originals
    assert not files
    view = wide_logs.WideLogView(_embed(), "", log_type="message_delete", media_items=media)
    assert not _components(view, discord.ui.MediaGallery)


def test_attachment_uri_without_actual_file_is_never_rendered_as_image():
    media = [("attachment://missing.png", "missing.png", "image/png")]
    view = wide_logs.WideLogView(_embed(), "", log_type="message_delete", media_items=media)
    assert not _components(view, discord.ui.MediaGallery)
    assert "Aperçu indisponible" in _text(view)


@pytest.mark.asyncio
async def test_oversized_deleted_images_are_skipped_before_http_download():
    image = _attachments(1)[0]
    image.size = 7 * 1024 * 1024
    items, uploads = await _snapshot_deleted_images([image], _attachment_media([image]))
    assert not uploads
    assert items[0][0] == image.url
    image.read.assert_not_awaited()


def test_wide_log_transport_checks_attachment_filenames_before_gallery():
    from pathlib import Path
    content = (Path(__file__).resolve().parents[1] / "utils" / "wide_logs.py").read_text()
    assert "available_attachments={" in content
    assert "for f in ([extra_file] if extra_file is not None else []) + list(extra_files or [])" in content
    source = (Path(__file__).resolve().parents[1] / "utils" / "log_service.py").read_text()
    assert "extra_files=media_files" in source
