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
    # La branche +setup est publique et vérifie les permissions AVANT
    # d'envoyer quoi que ce soit. La branche /setup continue de différer
    # en privé avant son propre contrôle de permissions.
    ack = code.index("await _prepare_private_setup_interaction(slash)")
    slash_check = code.index("await setup_ui._can_setup(", ack)
    assert ack < slash_check
    assert "Aucun panneau public n'a été envoyé" not in code
    assert "return await panels.envoyer(target.followup, view, ephemere=True)" in code
    assert "return await panels.envoyer(target, view, ephemere=True)" in code
    assert "return await panels.envoyer(target, view, ephemere=False)" in code
    assert "await setup_ui._can_setup(self.bot, member, guild)" in code
    assert "delete_after=15" not in code
    assert "PrivateSetupLauncher" not in code
    for name in ("cogs/setup_invitations.py", "cogs/ai.py", "cogs/ai_api_hotfix.py",
                 "cogs/ai_reply_recovery.py", "cogs/platform_v4.py"):
        ast.parse((ROOT / name).read_text(encoding="utf-8"), filename=name)


def test_custom_embed_has_real_thin_banner_above_not_extra_message():
    from utils.premium_log_banners import get_premium_log_banner
    path = get_premium_log_banner()
    assert path.exists()
    with Image.open(path) as banner:
        assert banner.size == (1200, 24)
    text = (ROOT / "cogs/platform_v4.py").read_text(encoding="utf-8")
    listener = text.split("    async def on_message(self, message:", 1)[1].split(
        "    # ----------------------------------------------------------- role menus", 1
    )[0]
    assert "from utils.premium_log_banners import BANNER_FILENAME, get_premium_log_banner" in listener
    assert "banner_name = BANNER_FILENAME" in listener
    assert 'nom_fichier("special")' not in listener
    assert "discord.Embed()" in listener
    assert "_sentrix_native_message=True" in listener
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
    # On FINALISE son original public avec un texte neutre sans le supprimer,
    # puis on envoie un NOUVEAU followup éphémère.
    old_defer = SimpleNamespace(
        response=SimpleNamespace(
            is_done=lambda: True,
            type=discord.InteractionResponseType.deferred_channel_message,
        ),
        delete_original_response=AsyncMock(),
        edit_original_response=AsyncMock(),
    )
    assert await _prepare_private_setup_interaction(old_defer) is True
    old_defer.delete_original_response.assert_not_awaited()
    old_defer.edit_original_response.assert_awaited_once_with(
        content="Ton panneau de configuration s'ouvre en privé.",
        embed=None, view=None,
    )

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



@pytest.mark.asyncio
async def test_real_production_v5_reply_reads_the_user_image_and_forwards_to_pipeline():
    """Le wrapper V5 était l'autorité réelle en production (log ai-reply).
    Le vieux test ne couvrait que Ai.send_sentrix_reply qui était remplacé.
    """
    from cogs import bot_experience_v5

    guild = SimpleNamespace(id=82)
    attachment = _attachment()
    author = SimpleNamespace(
        id=862, bot=False, display_name="Tomioka", roles=[],
    )
    channel = SimpleNamespace(id=112, guild=guild, send=AsyncMock())
    message = SimpleNamespace(
        id=539, content="sentrix analyse cette image",
        guild=guild, channel=channel, author=author,
        attachments=[attachment],
    )
    pipeline = AsyncMock(return_value={
        "ok": True, "text": "La capture contient le mot bienvenue.",
        "model_key": "luna",
    })
    # Reproduit la panne réelle : le runtime remplace la méthode de l'instance
    # par fast_prepare qui ne connaît pas image_urls.
    incompatible_fast_prepare = AsyncMock(
        side_effect=TypeError("fast_prepare() got an unexpected keyword argument 'image_urls'")
    )
    ai_cog = SimpleNamespace(
        _prepare_and_generate=incompatible_fast_prepare,
        histories={862: ["stale"]},
    )
    db = SimpleNamespace(is_bot_creator=AsyncMock(return_value=False))
    bot = SimpleNamespace(get_cog=lambda name: ai_cog if name == "Ai" else None,
                          db=db, user=SimpleNamespace(id=99),
                          blacklist_cache={})
    ai_cog.bot = bot

    with patch("cogs.bot_experience_v5.ai_service.get_settings",
               AsyncMock(return_value={"enabled": True})):
        with patch("cogs.bot_experience_v5.ai_service.is_channel_allowed",
                   return_value=True):
            with patch("cogs.bot_experience_v5.ai_service.is_role_allowed",
                       return_value=True):
                with patch("cogs.reply_reference_fix.send_native_ai_reply",
                           AsyncMock()) as deliver:
                    with patch("cogs.ai.CANONICAL_PREPARE_FOR_VISION", pipeline):
                        bot_experience_v5._install_ai_pipeline_upgrade(bot)
                        await ai_cog.send_sentrix_reply(
                            channel, author, "analyse cette image", reply_to=message,
                        )

    incompatible_fast_prepare.assert_not_awaited()
    images = pipeline.await_args.kwargs["image_urls"]
    assert len(images) == 1
    assert images[0].startswith("data:image/jpeg;base64,")
    deliver.assert_awaited_once()
    assert ai_cog.histories == {}
    attachment.read.assert_awaited()


@pytest.mark.asyncio
async def test_canonical_pipeline_sends_image_to_responses_api_instead_of_text_only():
    from cogs.ai import Ai
    from utils import ai_service

    bot = SimpleNamespace()
    ai_cog = SimpleNamespace(
        bot=bot,
        _check_cooldown=lambda *_args: None,
        _check_minute_limit=lambda *_args: False,
        _build_system_instructions=AsyncMock(return_value="System"),
    )
    model_result = SimpleNamespace(ok=True, text="L'image montre deux cartes.",
                                   model_key="luna", response_id="abc")
    screenshot = "data:image/jpeg;base64,ZGF0YQ=="

    with patch("cogs.ai.ai_service.generate", AsyncMock(return_value=model_result)) as generate:
        result = await Ai._prepare_and_generate(
            ai_cog, guild_id=None, channel_id=123, user_id=456,
            author_name="Tomioka", question="Décris la capture",
            command="ai-reply", image_urls=[screenshot],
        )

    assert result["ok"] is True
    payload = generate.await_args.args[0]
    assert payload[0]["content"][0]["type"] == "input_text"
    assert payload[0]["content"][1] == {
        "type": "input_image", "image_url": screenshot, "detail": "high"
    }
    assert "images fournies" in generate.await_args.kwargs["instructions"]


def test_prefix_setup_is_public_immediate_and_slash_remains_ephemeral():
    source = (ROOT / "cogs/setup_invitations.py").read_text(encoding="utf-8")
    block = source.split("    async def final_send_setup(self, target):", 1)[1].split(
        "    current = setup_ui.OfficialSetup.send_setup", 1
    )[0]
    prefix = block.split(
        "        # Discord ne sait pas envoyer un panneau éphémère", 1
    )[0]
    assert "target.interaction is None" in prefix
    assert "await setup_ui._can_setup(self.bot, member, guild)" in prefix
    assert "await view.prepare()" in prefix
    assert "return await panels.envoyer(target, view, ephemere=False)" in prefix
    assert "PrivateSetupLauncher" not in source
    # La commande slash /setup suit TOUJOURS le transport privé.
    assert "return await panels.envoyer(target.followup, view, ephemere=True)" in block
    assert "return await panels.envoyer(target, view, ephemere=True)" in block


def test_only_native_custom_messages_bypass_legacy_information_banner():
    policy = (ROOT / "cogs/plain_response_policy.py").read_text(encoding="utf-8")
    assert 'kwargs.pop("_sentrix_native_message", False)' in policy
    assert policy.index('kwargs.pop("_sentrix_native_message", False)') < policy.index(
        'ctx = _COMMAND_CONTEXT.get()', policy.index('async def absolute_messageable_send')
    )
    custom = (ROOT / "cogs/platform_v4.py").read_text(encoding="utf-8")
    assert 'embeds=[banner, embed]' in custom
    assert '_sentrix_native_message=True' in custom
    setup = (ROOT / "cogs/setup_invitations.py").read_text(encoding="utf-8")
    assert 'return await panels.envoyer(target, view, ephemere=False)' in setup
    assert 'PrivateSetupLauncher' not in setup



@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lang", "confirmation"),
    [
        ("fr", "**Ajouté par :** <@200>"),
        ("en", "**Added by:** <@200>"),
    ],
)
async def test_ticket_add_shows_exact_staff_member_and_audits_actor(lang, confirmation):
    from cogs import tickets
    selected_member = SimpleNamespace(id=300, mention="<@300>")
    staff = SimpleNamespace(id=200, mention="<@200>")
    chosen = SimpleNamespace(values=[selected_member], callback=None)
    fake_view = SimpleNamespace(add_item=lambda _item: None)
    guild = SimpleNamespace(id=100)
    channel = SimpleNamespace(set_permissions=AsyncMock())
    setup_interaction = SimpleNamespace(
        response=SimpleNamespace(send_message=AsyncMock()),
    )
    submit_interaction = SimpleNamespace(
        guild=guild, channel=channel, user=staff,
        response=SimpleNamespace(),
    )
    self = SimpleNamespace(bot=SimpleNamespace())
    with patch("cogs.tickets.discord.ui.UserSelect", return_value=chosen), patch(
        "cogs.tickets.discord.ui.View", return_value=fake_view
    ), patch("cogs.tickets.language_runtime.get_language", AsyncMock(return_value=lang)):
        with patch("cogs.tickets.sx_panels.envoyer", AsyncMock()) as sent, patch(
            "cogs.tickets.sx_panels.depuis_embed", side_effect=lambda e: e
        ), patch("cogs.tickets.tickets_service.journaliser_evenement", AsyncMock()) as audit:
            await tickets.Tickets.btn_add(self, setup_interaction, {"id": 18})
            assert setup_interaction.response.send_message.await_args.kwargs["ephemeral"]
            await chosen.callback(submit_interaction)
    channel.set_permissions.assert_awaited_once_with(
        selected_member, view_channel=True, send_messages=True,
        read_message_history=True,
    )
    embed = sent.await_args.args[1]
    assert confirmation in str(embed.to_dict())
    assert "<@300>" in str(embed.to_dict())
    assert audit.await_args.kwargs["acteur"] is staff
    assert audit.await_args.kwargs["cible"] is selected_member
    assert audit.await_args.kwargs["ticket_id"] == 18


@pytest.mark.asyncio
async def test_ticket_remove_shows_actor_and_audits_after_discord_success():
    from cogs import tickets
    member = SimpleNamespace(id=300, mention="<@300>")
    staff = SimpleNamespace(id=200, mention="<@200>")
    selected = SimpleNamespace(values=[member], callback=None)
    guild = SimpleNamespace(id=100)
    channel = SimpleNamespace(set_permissions=AsyncMock())
    setup = SimpleNamespace(response=SimpleNamespace(send_message=AsyncMock()))
    inter = SimpleNamespace(guild=guild, channel=channel, user=staff,
                            response=SimpleNamespace())
    with patch("cogs.tickets.discord.ui.UserSelect", return_value=selected), patch(
        "cogs.tickets.discord.ui.View", return_value=SimpleNamespace(add_item=lambda _: None)
    ), patch("cogs.tickets.language_runtime.get_language", AsyncMock(return_value="fr")):
        with patch("cogs.tickets.sx_panels.envoyer", AsyncMock()) as sent, patch(
            "cogs.tickets.sx_panels.depuis_embed", side_effect=lambda e: e
        ), patch("cogs.tickets.tickets_service.journaliser_evenement", AsyncMock()) as audit:
            await tickets.Tickets.btn_remove(SimpleNamespace(bot=SimpleNamespace()),
                                             setup, {"id": 18, "user_id": 400})
            await selected.callback(inter)
    channel.set_permissions.assert_awaited_once_with(member, overwrite=None)
    assert "**Retiré par :** <@200>" in str(sent.await_args.args[1].to_dict())
    assert audit.await_args.args[2] == "ticket_member_remove"
    assert audit.await_args.kwargs["acteur"] is staff


def test_english_french_language_defaults_and_safe_duplicate_command_removal():
    import discord
    from discord.ext import commands
    from cogs import commandes_retirees, language_runtime

    assert language_runtime.DEFAULT_LANGUAGE == language_runtime.LANG_FR == "fr"
    assert language_runtime.text_for_language(
        language_runtime.DEFAULT_LANGUAGE, "Bonjour", "Hello"
    ) == "Bonjour"
    assert language_runtime.text_for_language("en", "Bonjour", "Hello") == "Hello"

    duplicates = {
        "ask", "chat", "rank", "buyrole", "embed-create",
        "latency", "levelroles", "roleinfo",
    }
    assert duplicates <= commandes_retirees.A_RETIRER
    bot = commands.Bot(command_prefix="+", intents=discord.Intents.none())

    async def noop(ctx):
        return None

    for name in duplicates | {"ping", "help", "ai", "level"}:
        if name == "help":
            continue  # discord.py enregistre déjà son aide intégrée
        bot.command(name=name)(noop)
    removed = commandes_retirees.retirer(bot)
    assert duplicates <= set(removed)
    for name in duplicates:
        assert bot.get_command(name) is None
    for name in ("ping", "ai", "level"):
        assert bot.get_command(name) is not None
