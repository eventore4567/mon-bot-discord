from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from cogs.logs import Logs, _attach_message_transcript
from utils import wide_logs


def _setup():
    guild = SimpleNamespace(id=100, get_member=lambda _id: None)
    bot = SimpleNamespace(db=SimpleNamespace(execute=AsyncMock()))
    cog = Logs(bot)
    cog._send = AsyncMock(return_value=True)
    cog._message_delete_actor = AsyncMock(return_value=(None, None))
    cog._forget_cached_message = AsyncMock()
    author = SimpleNamespace(id=200, bot=False, display_name="Membre", display_avatar=None)
    message = SimpleNamespace(id=300, guild=guild, channel=SimpleNamespace(id=400), author=author,
                              content="", attachments=[], jump_url="https://discord.com/channels/100/400/300", edited_at=None)
    return cog, message


def _text(cog):
    return cog._send.await_args.kwargs["media_files"][0].fp.getvalue().decode("utf-8")


@pytest.mark.asyncio
async def test_deleted_message_keeps_exact_full_unicode_and_whitespace():
    cog, message = _setup()
    content = "  début\n``` @everyone <@123> é🙂 " + "Texte long **" * 400 + "\nFIN  "
    message.content = content
    await cog.on_message_delete(message)
    text = _text(cog)
    assert f"===== Contenu =====\n{content}\n" in text
    assert "Message : 300" in text and "Auteur : 200" in text
    files = cog._send.await_args.kwargs["media_files"]
    media = cog._send.await_args.kwargs["media_items"]
    assert media[0][0] == f"attachment://{files[0].filename}"
    cog._forget_cached_message.assert_awaited_once_with(300)


@pytest.mark.asyncio
async def test_edited_log_contains_both_versions_even_if_only_one_is_long():
    cog, before = _setup()
    before.content = "texte initial " * 600
    after = SimpleNamespace(**vars(before))
    after.content = "court après modification"
    await cog.on_message_edit(before, after)
    assert f"===== Avant =====\n{before.content}\n" in _text(cog)
    assert f"===== Après =====\n{after.content}\n" in _text(cog)


@pytest.mark.asyncio
async def test_persistent_cache_recovery_also_attaches_full_transcript():
    cog, message = _setup()
    content = "très long message récupéré " * 300
    row = {"message_id": 300, "channel_id": 400, "author_id": 200,
           "author_name": "Membre", "content": content,
           "attachments": '["https://example.com/original.png"]'}
    assert await cog._log_deleted_from_row(message.guild, row)
    assert content in _text(cog)
    assert "https://example.com/original.png" in _text(cog)


@pytest.mark.asyncio
async def test_short_message_has_no_unnecessary_transcript():
    cog, message = _setup()
    message.content = "Salut !"
    await cog.on_message_delete(message)
    assert cog._send.await_args.kwargs["media_files"] == []


@pytest.mark.asyncio
async def test_failed_send_does_not_erase_the_cached_evidence():
    cog, message = _setup()
    message.content = "preuve " * 500
    cog._send.return_value = False
    await cog.on_message_delete(message)
    cog._forget_cached_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_transcript_is_visible_as_downloadable_components_v2_file():
    panel = discord.Embed(title="Message supprimé")
    panel.add_field(name="Contenu", value="aperçu")
    media, files = _attach_message_transcript(
        panel, guild_id=100, channel_id=400, message_id=300, author_id=200,
        sections=[("Contenu", "long " * 300)],
    )
    view = wide_logs.WideLogView(panel, banner_filename="", log_type="message_delete",
                                 media_items=media, available_attachments={files[0].filename})
    def walk(children):
        for child in children:
            yield child
            yield from walk(getattr(child, "children", []))
    assert any(isinstance(child, discord.ui.File) for child in walk(view.children))


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["*" * 800, "court\n" * 25])
async def test_expanded_markdown_and_many_lines_also_get_a_transcript(content):
    cog, message = _setup()
    message.content = content
    await cog.on_message_delete(message)
    assert content in _text(cog)
