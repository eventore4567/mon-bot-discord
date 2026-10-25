"""Native Discord replies and author notifications from the ACTIVE V5 AI pipeline."""
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
from cogs import bot_experience_v5 as v5


def _install_pipeline(*, text="Salut !"):
    author = SimpleNamespace(id=14, mention="<@14>", display_name="Tomioka")
    guild = SimpleNamespace(id=10)
    channel = SimpleNamespace(id=20, guild=guild, send=AsyncMock(return_value=None))
    bot = SimpleNamespace(user=SimpleNamespace(id=999))
    ai_cog = SimpleNamespace(
        bot=bot,
        histories={},
        _prepare_and_generate=AsyncMock(return_value={"ok": True, "text": text}),
    )
    bot.get_cog = lambda name: ai_cog if name == "Ai" else None
    v5._install_ai_pipeline_upgrade(bot)
    message = SimpleNamespace(
        id=30, guild=guild, channel=channel,
        author=author, content="sentrix yo",
        reply=AsyncMock(return_value=None),
    )
    return ai_cog, author, channel, message


@pytest.mark.asyncio
async def test_passive_mention_replies_natively_and_notifies_only_author():
    ai, author, channel, message = _install_pipeline()
    with patch.object(v5, "_is_blacklisted", AsyncMock(return_value=False)), \
         patch.object(v5, "_ai_access_error", AsyncMock(return_value=None)):
        await ai.send_sentrix_reply(channel, author, "yo", reply_to=message)
    message.reply.assert_awaited_once()
    kwargs = message.reply.await_args.kwargs
    assert kwargs["mention_author"] is True
    assert kwargs["allowed_mentions"].everyone is False
    assert kwargs["allowed_mentions"].roles is False
    assert kwargs["allowed_mentions"].users == [author]
    assert kwargs["allowed_mentions"].replied_user is True
    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_long_answer_only_replies_once():
    ai, author, channel, message = _install_pipeline(text="long")
    with patch.object(v5, "_is_blacklisted", AsyncMock(return_value=False)), \
         patch.object(v5, "_ai_access_error", AsyncMock(return_value=None)), \
         patch.object(v5.ai_service, "split_for_discord", return_value=["partie 1", "partie 2"]):
        await ai.send_sentrix_reply(channel, author, "question", reply_to=message)
    message.reply.assert_awaited_once()
    channel.send.assert_awaited_once()
    assert channel.send.await_args.kwargs["allowed_mentions"].to_dict() == {"parse": []}


@pytest.mark.asyncio
async def test_discord_reference_error_fallback_still_pings_only_author():
    ai, author, channel, message = _install_pipeline()
    response = MagicMock()
    response.status = 400
    response.reason = "Bad Request"
    message.reply.side_effect = discord.HTTPException(response, {"message": "Unknown Message", "code": 10008})
    with patch.object(v5, "_is_blacklisted", AsyncMock(return_value=False)), \
         patch.object(v5, "_ai_access_error", AsyncMock(return_value=None)):
        await ai.send_sentrix_reply(channel, author, "yo", reply_to=message)
    channel.send.assert_awaited_once()
    sent = channel.send.await_args.kwargs
    assert sent["content"].startswith("<@14> ")
    assert sent["allowed_mentions"].users == [author]
    assert sent["allowed_mentions"].everyone is False
    assert sent["allowed_mentions"].roles is False


def test_reference_middleware_keeps_ai_context_explicit_and_private():
    from cogs import reply_reference_fix as guard
    assert guard._NATIVE_AI_REPLY.get() is False
    assert "reference" not in guard._clean_reference_kwargs({"reference": 1})
    token = guard._NATIVE_AI_REPLY.set(True)
    try:
        assert guard._clean_reference_kwargs({"reference": 1})["reference"] == 1
    finally:
        guard._NATIVE_AI_REPLY.reset(token)


@pytest.mark.asyncio
async def test_installed_reference_filter_preserves_only_explicit_ai_reply(monkeypatch):
    """Exercise the actual discord.py Message.reply and Messageable.send patch stack."""
    from cogs import reply_reference_fix as guard
    from discord.ext import commands

    observed = []

    async def original_channel_send(_self, *args, **kwargs):
        observed.append(dict(kwargs))
        return SimpleNamespace(reference=kwargs.get("reference"))

    async def original_message_reply(_self, *args, **kwargs):
        raise AssertionError("The middleware should replace Discord Message.reply")

    class Channel:
        async def send(self, *args, **kwargs):
            return await discord.abc.Messageable.send(self, *args, **kwargs)

    class Message:
        channel = Channel()

        def to_reference(self, *, fail_if_not_exists=False):
            return ("ref", 777, fail_if_not_exists)

        async def reply(self, *args, **kwargs):
            return await discord.Message.reply(self, *args, **kwargs)

    was_installed = guard._INSTALLED
    try:
        with monkeypatch.context() as mp:
            mp.setattr(discord.abc.Messageable, "send", original_channel_send)
            mp.setattr(discord.Message, "reply", original_message_reply)
            mp.setattr(commands.Context, "send", original_channel_send)
            mp.setattr(commands.Context, "reply", original_message_reply)
            guard._INSTALLED = False
            guard.install()
            message = Message()
            await guard.send_native_ai_reply(message, content="Bonjour", mention_author=True)
            await message.reply(content="Message normal", mention_author=True)
            await message.channel.send(content="Envoi normal", reference="no")
    finally:
        guard._INSTALLED = was_installed

    assert observed[0]["reference"] == ("ref", 777, False)
    assert observed[0]["mention_author"] is True
    assert "reference" not in observed[1]
    assert "reference" not in observed[2]
