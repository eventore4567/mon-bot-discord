"""Contrats réels : /setup privé, bannière embed, images multimodales Discord."""
from __future__ import annotations

import ast
import io
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
ROOT = Path(__file__).resolve().parents[1]


def _attachment(*, mime="application/octet-stream"):
    out = io.BytesIO()
    Image.new("RGB", (96, 58), (18, 85, 125)).save(out, format="PNG")
    data = out.getvalue()
    return SimpleNamespace(
        filename="capture.png", content_type=mime, size=len(data),
        read=AsyncMock(return_value=data),
    )


@pytest.mark.asyncio
async def test_image_de_discord_reply_to_reaches_model_even_when_contextvar_empty():
    from cogs.ai import Ai, _PASSIVE_IMAGE_CONTEXT

    attachment = _attachment()
    author = SimpleNamespace(id=12, display_name="Tomioka")
    guild = SimpleNamespace(id=34)
    channel = SimpleNamespace(id=56, guild=guild, send=AsyncMock())
    source = SimpleNamespace(
        id=78, channel=channel, guild=guild,
        author=author, attachments=[attachment],
    )
    cog = SimpleNamespace(
        histories={}, ask_ai=AsyncMock(return_value="Je vois le message Ok."),
    )
    token = _PASSIVE_IMAGE_CONTEXT.set(())
    try:
        await Ai.send_sentrix_reply(cog, channel, author, "Décris cette image", reply_to=source)
    finally:
        _PASSIVE_IMAGE_CONTEXT.reset(token)
    image_urls = cog.ask_ai.await_args.kwargs["image_urls"]
    assert len(image_urls) == 1
    assert image_urls[0].startswith("data:image/jpeg;base64,")
    attachment.read.assert_awaited()
    channel.send.assert_awaited()


@pytest.mark.asyncio
async def test_image_capture_est_acceptee_meme_si_discord_donne_un_mime_generique():
    from cogs.ai import _images_from_discord_attachments
    attachment = _attachment()
    images = await _images_from_discord_attachments([attachment])
    assert len(images) == 1
    assert images[0].startswith("data:image/jpeg;base64,")


@pytest.mark.asyncio
async def test_ai_recovery_uses_actual_multimodal_input_from_original_message():
    from cogs.ai_reply_recovery import _direct_reply

    attachment = _attachment(mime="image/png")
    author = SimpleNamespace(id=12, display_name="Tomioka")
    guild = SimpleNamespace(id=34)
    channel = SimpleNamespace(id=56, guild=guild)
    source = SimpleNamespace(
        id=78, channel=channel, guild=guild,
        author=author, attachments=[attachment],
    )
    bot = SimpleNamespace(get_cog=lambda _name: None)
    result = SimpleNamespace(ok=True, text="La capture montre un embed.")
    with patch("cogs.ai_reply_recovery.ai_service.generate", AsyncMock(return_value=result)) as generate:
        with patch("cogs.ai_reply_recovery._send_text", AsyncMock()) as send:
            await _direct_reply(bot, channel, author, "Décris cette image", reply_to=source)
    payload = generate.await_args.args[0]
    assert payload[0]["content"][1]["type"] == "input_image"
    assert payload[0]["content"][1]["image_url"].startswith("data:image/jpeg;base64,")
    send.assert_awaited()


def test_final_setup_private_from_first_interaction_ack():
    src = (ROOT / "cogs/setup_invitations.py").read_text(encoding="utf-8")
    start = src.index("    async def final_send_setup(self, target):")
    end = src.index("    current = setup_ui.OfficialSetup.send_setup", start)
    code = src[start:end]
    assert "await _prepare_private_setup_interaction(slash)" in code
    assert code.index("await _prepare_private_setup_interaction(slash)") < code.index(
        "await setup_ui._can_setup("
    )
    assert "Aucun panneau public n'a été envoyé" not in code
    assert "return await panels.envoyer(target.followup, view, ephemere=True)" in code
    assert "return await panels.envoyer(target, view, ephemere=True)" in code
    assert "delete_after=15" in code
    for name in ("cogs/setup_invitations.py", "cogs/ai.py", "cogs/ai_api_hotfix.py",
                 "cogs/ai_reply_recovery.py", "cogs/platform_v4.py"):
        ast.parse((ROOT / name).read_text(encoding="utf-8"), filename=name)


def test_custom_embed_has_real_thin_banner_above_not_extra_message():
    from utils.log_banners import BANNER_DIR, ensure_banners, nom_fichier
    ensure_banners()
    path = BANNER_DIR / nom_fichier("special")
    assert path.exists()
    with Image.open(path) as banner:
        assert banner.width >= 1000
        assert banner.height <= 80
    text = (ROOT / "cogs/platform_v4.py").read_text(encoding="utf-8")
    listener = text.split("    async def on_message(self, message:", 1)[1].split(
        "    # ----------------------------------------------------------- role menus", 1
    )[0]
    assert 'banner_name = nom_fichier("special")' in listener
    assert 'banner.set_image(url=f"attachment://{banner_name}")' in listener
    assert "embeds=[banner, embed]" in listener
    assert "file=banner_file" in listener
    assert "banner_file.close()" in listener
    assert "if row[\"embed_title\"]:" in listener



@pytest.mark.asyncio
async def test_slash_setup_ack_private_and_recover_unknown_deferred_without_public_panel():
    import discord
    from cogs.setup_invitations import (
        _KNOWN_PRIVATE_SETUP_ACK, _prepare_private_setup_interaction,
    )

    fresh = SimpleNamespace(
        response=SimpleNamespace(is_done=lambda: False, defer=AsyncMock(), type=None),
        delete_original_response=AsyncMock(),
    )
    assert await _prepare_private_setup_interaction(fresh) is False
    fresh.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    fresh.delete_original_response.assert_not_awaited()

    # Régression des captures : un autre chemin avait déjà consommé /setup.
    # On supprime son original (éventuellement PUBLIC), puis on envoie un
    # NOUVEAU followup éphémère. Plus de demande « relance /setup ».
    old_defer = SimpleNamespace(
        response=SimpleNamespace(
            is_done=lambda: True,
            type=discord.InteractionResponseType.deferred_channel_message,
        ),
        delete_original_response=AsyncMock(),
    )
    assert await _prepare_private_setup_interaction(old_defer) is True
    old_defer.delete_original_response.assert_awaited_once()

    private = SimpleNamespace(
        response=SimpleNamespace(
            is_done=lambda: True,
            type=discord.InteractionResponseType.deferred_channel_message,
        ),
        delete_original_response=AsyncMock(),
    )
    token = _KNOWN_PRIVATE_SETUP_ACK.set(True)
    try:
        assert await _prepare_private_setup_interaction(private) is False
    finally:
        _KNOWN_PRIVATE_SETUP_ACK.reset(token)
    private.delete_original_response.assert_not_awaited()

    already_answered = SimpleNamespace(
        response=SimpleNamespace(
            is_done=lambda: True,
            type=discord.InteractionResponseType.channel_message,
        ),
        delete_original_response=AsyncMock(),
    )
    assert await _prepare_private_setup_interaction(already_answered) is True
    already_answered.delete_original_response.assert_not_awaited()


class _Typing:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


@pytest.mark.asyncio
async def test_image_only_reply_with_uncached_discord_reference_reaches_vision_model():
    from cogs.ai import Ai, _PASSIVE_IMAGE_CONTEXT, _PENDING_IMAGE_FOLLOWUPS

    attachment = _attachment()
    guild = SimpleNamespace(id=853)
    user = SimpleNamespace(id=937, bot=False, display_name="Tomioka")
    bot_user = SimpleNamespace(id=203)
    fetched = SimpleNamespace(author=bot_user)
    channel = SimpleNamespace(
        id=409, guild=guild, typing=lambda: _Typing(),
        fetch_message=AsyncMock(return_value=fetched),
    )
    message = SimpleNamespace(
        id=562, guild=guild, channel=channel,
        author=user, content="", mentions=[], attachments=[attachment],
        reference=SimpleNamespace(message_id=777, resolved=None),
    )
    bot = SimpleNamespace(user=bot_user, prefix_cache={guild.id: "+"})
    vision_calls = []

    async def fake_reply(destination, author, question, *, reply_to):
        vision_calls.append((destination, author, question, reply_to,
                             list(_PASSIVE_IMAGE_CONTEXT.get())))

    cog = SimpleNamespace(
        bot=bot, _channel_blocks_ai=AsyncMock(return_value=False),
        _invoke_natural_command=AsyncMock(return_value=False),
        send_sentrix_reply=fake_reply,
    )
    _PENDING_IMAGE_FOLLOWUPS.clear()
    with patch("cogs.ai.ai_service.get_settings", AsyncMock(return_value={"enabled": True})):
        with patch("cogs.ai.ai_service.is_channel_allowed", return_value=True):
            await Ai.on_message(cog, message)

    channel.fetch_message.assert_awaited_once_with(777)
    assert len(vision_calls) == 1
    assert vision_calls[0][3] is message
    assert vision_calls[0][2] == "Décris cette image."
    assert vision_calls[0][4][0].startswith("data:image/jpeg;base64,")
    attachment.read.assert_awaited()


@pytest.mark.asyncio
async def test_broad_image_request_remembers_followup_even_without_word_image():
    from cogs.ai import Ai, _PENDING_IMAGE_FOLLOWUPS

    guild = SimpleNamespace(id=854)
    author = SimpleNamespace(id=938, bot=False)
    bot_user = SimpleNamespace(id=203)
    channel = SimpleNamespace(id=410, typing=lambda: _Typing())
    msg = SimpleNamespace(
        id=568, guild=guild, channel=channel, author=author,
        content="SentriX examine tout", mentions=[], attachments=[], reference=None,
    )
    bot = SimpleNamespace(user=bot_user, prefix_cache={guild.id: "+"})
    cog = SimpleNamespace(
        bot=bot, _channel_blocks_ai=AsyncMock(return_value=False),
        _invoke_natural_command=AsyncMock(return_value=False),
        send_sentrix_reply=AsyncMock(),
    )
    key = (guild.id, channel.id, author.id)
    _PENDING_IMAGE_FOLLOWUPS.pop(key, None)
    try:
        with patch("cogs.ai.ai_service.get_settings", AsyncMock(return_value={"enabled": True})):
            with patch("cogs.ai.ai_service.is_channel_allowed", return_value=True):
                await Ai.on_message(cog, msg)
        assert key in _PENDING_IMAGE_FOLLOWUPS
        assert _PENDING_IMAGE_FOLLOWUPS[key][1] == "examine tout"
    finally:
        _PENDING_IMAGE_FOLLOWUPS.pop(key, None)
