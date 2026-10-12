"""Régressions des images supprimées et de la durée des timeouts.

Les liens CDN d'un message supprimé peuvent expirer : une grille de quatre
cases cassées ne doit jamais être envoyée comme si les images existaient.
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from cogs.logs import _snapshot_deleted_images, _timeout_duration_label
from utils import wide_logs


def _gallery_count(view: discord.ui.LayoutView) -> int:
    def walk(children):
        for item in children or []:
            if isinstance(item, discord.ui.MediaGallery):
                yield item
            yield from walk(getattr(item, "children", None))
    return len(list(walk(view.children)))


def _text(view: discord.ui.LayoutView) -> str:
    chunks = []
    def walk(children):
        for item in children or []:
            if isinstance(item, discord.ui.TextDisplay):
                chunks.append(item.content)
            walk(getattr(item, "children", None))
    walk(view.children)
    return "\n".join(chunks)


def _log(media, *, available=None):
    embed = discord.Embed(title="Message supprimé")
    embed.add_field(name="Auteur", value="<@123456789012345678>")
    embed.add_field(name="Contenu", value="Message contenant des images")
    return wide_logs.WideLogView(
        embed, banner_filename="", log_type="message_delete",
        media_items=media, available_attachments=available,
    )


def test_expired_external_media_not_rendered_as_broken_gallery():
    media = [
        (f"https://cdn.discordapp.com/attachments/1/2/photo-{i}.png?ex=expired",
         f"photo-{i}.png", "image/png")
        for i in range(4)
    ]
    view = _log(media)
    assert _gallery_count(view) == 0
    text = _text(view)
    assert "Aperçu non conservé" in text
    assert "Ouvrir photo-0.png" in text
    assert "## Message supprimé" in text


def test_only_attached_local_media_appear_in_gallery():
    media = [
        ("attachment://sentrix-log-image-1.png", "a.png", "image/png"),
        ("attachment://sentrix-log-image-2.png", "b.png", "image/png"),
        ("https://cdn.discordapp.com/attachments/1/2/deleted.png",
         "deleted.png", "image/png"),
    ]
    view = _log(media, available={"sentrix-log-image-1.png"})
    assert _gallery_count(view) == 1
    text = _text(view)
    assert "Ouvrir deleted.png" in text
    assert "Aperçu non conservé" in text
    assert "b.png" in text  # missing local file falls back to a label


@pytest.mark.asyncio
async def test_snapshot_of_live_attachment_creates_a_local_discord_file():
    blob = b"\x89PNG\r\n\x1a\nvalid-test-image"
    a = SimpleNamespace(size=len(blob), read=AsyncMock(return_value=blob))
    items = [("https://cdn.discordapp.com/attachments/1/2/pic.png",
              "pic.png", "image/png")]
    media, files = await _snapshot_deleted_images([a], items)
    assert media == [
        ("attachment://sentrix-log-image-1.png", "pic.png", "image/png"),
    ]
    assert len(files) == 1
    assert files[0].filename == "sentrix-log-image-1.png"
    assert files[0].fp.read() == blob
    for f in files:
        f.close()


@pytest.mark.asyncio
async def test_unavailable_image_falls_back_without_gallery_attachment():
    a = SimpleNamespace(size=1024, read=AsyncMock(side_effect=discord.Forbidden(
        SimpleNamespace(status=403, reason="forbidden", headers={}), "Expired"
    )))
    media = [("https://cdn.discordapp.com/attachments/1/2/p.png", "p.png", "image/png")]
    new_media, files = await _snapshot_deleted_images([a], media)
    assert not files
    assert new_media == media


def test_timeout_duration_remaining_is_accurate_and_readable():
    now = datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc)
    assert _timeout_duration_label(now + timedelta(seconds=30), now=now) == "30 s"
    assert _timeout_duration_label(now + timedelta(minutes=10), now=now) == "10 min"
    assert _timeout_duration_label(now + timedelta(hours=1, minutes=15), now=now) == "1 h 15 min"
    assert _timeout_duration_label(now + timedelta(days=2, hours=3), now=now) == "2 j 3 h"
    assert _timeout_duration_label(now - timedelta(seconds=1), now=now) is None


def test_timeout_log_mentions_duration_and_keeps_moderator():
    embed = discord.Embed(title="Timeout appliqué")
    embed.add_field(name="Membre", value="<@123456789012345678>")
    embed.add_field(name="Modérateur", value="<@123456789012345679>")
    embed.add_field(name="Durée restante", value="10 min")
    embed.add_field(name="Fin prévue", value="<t:1791835800:F>")
    sentence = wide_logs.narrative_body(embed, log_type="member_timeout")
    assert "10 min" in sentence
    assert "<@123456789012345679>" in sentence
