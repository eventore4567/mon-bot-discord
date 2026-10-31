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
async def test_short_message_does_not_create_an_unnecessary_transcript():
    cog, message = _setup()
    message.content = ";;"
    await cog.on_message_delete(message)
    sent = cog._send.await_args
    assert sent.kwargs["media_files"] == []
    assert sent.kwargs["media_items"] == []
    panel = sent.args[2]
    assert any(field.name == "Contenu" and field.value == ";;" for field in panel.fields)
    assert not any(field.name == "Transcript" for field in panel.fields)


@pytest.mark.asyncio
async def test_short_edit_does_not_create_a_transcript():
    cog, before = _setup()
    before.content = "Avant"
    after = SimpleNamespace(**vars(before))
    after.content = "Après"
    await cog.on_message_edit(before, after)
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


@pytest.mark.asyncio
async def test_transcript_action_reads_actual_attachment_and_returns_download_link():
    from cogs.log_history_center import PremiumLogAction
    attachment = SimpleNamespace(filename="sentrix-message-300-transcript.txt",
                                 url="https://cdn.discordapp.com/attachments/test/transcript.txt")
    interaction = SimpleNamespace(
        guild_id=100000000000000100,
        message=SimpleNamespace(attachments=[attachment]),
        response=SimpleNamespace(send_message=AsyncMock()),
    )
    action = PremiumLogAction("transcript", 100000000000000100, 100000000000000200)
    await action.callback(interaction)
    result = interaction.response.send_message.await_args.kwargs
    assert result["ephemeral"] is True
    assert result["view"].children[0].url == attachment.url


@pytest.mark.asyncio
async def test_transcript_action_has_explicit_message_for_old_logs():
    from cogs.log_history_center import PremiumLogAction
    interaction = SimpleNamespace(
        guild_id=100000000000000100, message=SimpleNamespace(attachments=[]),
        response=SimpleNamespace(send_message=AsyncMock()),
    )
    await PremiumLogAction("transcript", 100000000000000100, 100000000000000200).callback(interaction)
    assert "ne contient pas de transcript" in interaction.response.send_message.await_args.args[0]


@pytest.mark.asyncio
async def test_message_log_keeps_downloadable_file_without_duplicate_transcript_button():
    from cogs.log_history_center import PremiumLogAction
    embed = discord.Embed(title="Message supprimé")
    media, files = _attach_message_transcript(
        embed, guild_id=100000000000000100, channel_id=400, message_id=300, author_id=200,
        sections=[("Contenu", "long " * 300)],
    )
    view = wide_logs.WideLogView(
        embed, banner_filename="", log_type="message_delete", guild_id=100000000000000100,
        identity_id=100000000000000200, media_items=media, available_attachments={files[0].filename},
    )
    def walk(items):
        for item in items:
            yield item
            yield from walk(getattr(item, "children", ()))
    children = list(walk(view.children))
    assert any(isinstance(item, discord.ui.File) for item in children)
    assert not any(isinstance(item, PremiumLogAction) and item.action == "transcript" for item in children)


@pytest.mark.asyncio
async def test_short_message_preserves_image_attachment_when_no_transcript():
    cog, message = _setup()
    message.content = "Photo"
    media_url = "https://cdn.discordapp.com/attachments/100/300/img.png"
    message.attachments = [SimpleNamespace(
        url=media_url, filename="img.png", content_type="image/png",
        size=8, read=AsyncMock(return_value=b"PNG data")
    )]
    await cog.on_message_delete(message)
    files = cog._send.await_args.kwargs["media_files"]
    assert files and all("transcript" not in file.filename for file in files)
    assert cog._send.await_args.kwargs["media_items"][0][1] == "img.png"
