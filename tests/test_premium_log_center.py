"""Contrats du journal premium SentriX, indépendants de l'API Discord."""
import asyncio
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from cogs.log_history_center import PremiumLogAction, MemberHistoryView
from utils.wide_logs import WideLogView, narrative_body, send_wide_log


GUILD_ID = 123456789012345678
USER_ID = 223456789012345678


def _walk(node):
    yield node
    for child in getattr(node, "children", []):
        yield from _walk(child)


def _embed(log_type="member_ban"):
    embed = discord.Embed(title="Dossier #42 — Membre banni")
    embed.add_field(name="Membre", value=f"<@{USER_ID}>")
    embed.add_field(name="Modérateur", value="<@323456789012345678>")
    embed.add_field(name="Raison", value="Spam répété")
    return embed


def test_equilibre_voice_log_keeps_side_avatar_without_blank_banner():
    embed = discord.Embed(title="Entrée en vocal")
    embed.add_field(name="Membre", value=f"<@{USER_ID}>")
    embed.add_field(name="Salon", value="<#323456789012345678>")
    view = WideLogView(
        embed,
        "legacy-banner.png",  # Non pris en compte dans Équilibré.
        identity_id=USER_ID,
        identity_name="moussa",
        identity_icon="https://cdn.discordapp.com/embed/avatars/0.png",
        log_type="voice_join",
    )
    items = list(_walk(view))
    assert any(isinstance(item, discord.ui.Section) for item in items)
    assert not any(isinstance(item, discord.ui.MediaGallery) for item in items)
    assert sum(isinstance(item, discord.ui.Separator) for item in items) >= 2
    content = "\n".join(str(getattr(item, "content", "")) for item in items)
    assert content.count(f"<@{USER_ID}>") == 1
    assert "A rejoint" in content
    assert "\n> " not in content
    assert "legacy-banner.webp" not in content


def test_transport_sends_no_decorative_image_and_keeps_balanced_layout():
    embed = discord.Embed(title="Entrée en vocal")
    embed.add_field(name="Membre", value=f"<@{USER_ID}>")
    embed.add_field(name="Salon", value="<#323456789012345678>")
    channel = SimpleNamespace(
        id=223456789012345678,
        guild=None,
        send=AsyncMock(return_value=SimpleNamespace(id=123, flags=SimpleNamespace(value=32768))),
    )
    ok = asyncio.run(send_wide_log(channel, embed, log_type="voice_join", identity_id=USER_ID))
    assert ok is True
    kwargs = channel.send.call_args.kwargs
    assert kwargs["files"] == []
    assert isinstance(kwargs["view"], WideLogView)
    assert not any(isinstance(x, discord.ui.MediaGallery)
                   for x in _walk(kwargs["view"]))



def test_all_log_categories_share_equilibre_no_blank_media_gallery():
    # Toutes les familles passent par send_wide_log, sans galerie décorative.
    categories = (
        "voice_join", "voice_leave", "voice_move", "member_ban",
        "member_unban", "member_warn", "member_timeout", "member_kick",
        "member_join", "member_leave", "message_delete", "message_edit",
        "role_add", "role_update", "channel_create", "channel_delete",
        "invite_create", "invite_delete", "ticket_open", "ticket_close",
        "automod_link", "automod_spam", "raid_detected", "guild_update",
        "soundboard_play",
    )
    async def check():
        for event in categories:
            embed = discord.Embed(title="Événement de test")
            channel = SimpleNamespace(
                id=223456789012345678, guild=None,
                send=AsyncMock(return_value=SimpleNamespace(
                    id=124, flags=SimpleNamespace(value=32768),
                )),
            )
            ok = await send_wide_log(channel, embed, log_type=event)
            assert ok is True, event
            kwargs = channel.send.call_args.kwargs
            assert kwargs["files"] == [], event
            view = kwargs["view"]
            assert isinstance(view, WideLogView), event
            children = list(_walk(view))
            assert not any(isinstance(i, discord.ui.MediaGallery)
                           for i in children), event
            assert any(isinstance(i, discord.ui.Separator)
                       for i in children), event
            content = "\\n".join(
                str(getattr(i, "content", "")) for i in children
            )
            assert "SENTRIX TRACE" not in content, event
            assert "BANNER" not in content, event
    asyncio.run(check())


def test_ten_real_files_are_preserved_without_a_banner():
    embed = discord.Embed(title="Message supprimé")
    attachments = [
        discord.File(io.BytesIO(f"file{i}".encode()), filename=f"image{i}.png")
        for i in range(10)
    ]
    channel = SimpleNamespace(
        id=223456789012345678,
        guild=None,
        send=AsyncMock(return_value=SimpleNamespace(
            id=125, flags=SimpleNamespace(value=32768),
        )),
    )
    ok = asyncio.run(send_wide_log(
        channel, embed, log_type="message_delete", extra_files=attachments,
    ))
    assert ok
    files = channel.send.call_args.kwargs["files"]
    assert len(files) == 10
    assert all(file.filename.startswith("image") for file in files)
    assert not any(isinstance(i, discord.ui.MediaGallery)
                   for i in _walk(channel.send.call_args.kwargs["view"]))
    for file in files:
        file.close()



def test_premium_log_has_persistent_history_and_unban_buttons_without_reference():
    view = WideLogView(
        _embed(), "",
        identity_name="moussa", identity_id=USER_ID,
        log_type="member_ban", guild_id=GUILD_ID,
    )
    items = list(_walk(view))
    actions = [i for i in items if isinstance(i, PremiumLogAction)]
    assert {a.action for a in actions} == {"history", "unban"}
    assert all(str(GUILD_ID) in a.item.custom_id for a in actions)
    text = "\n".join(
        str(getattr(i, "content", "")) for i in items
    )
    assert "Dossier #42" not in text
    assert "BAN-0042" not in text


def test_departure_displays_old_roles_and_stay():
    embed = discord.Embed(title="Membre parti")
    embed.add_field(name="Membre", value=f"<@{USER_ID}>")
    embed.add_field(name="Présence", value="4 jours")
    embed.add_field(name="Rôles avant le départ", value="<@&423456789012345678>, <@&523456789012345678>")
    body = narrative_body(embed, log_type="member_leave", identity_id=USER_ID)
    assert "Rôles avant le départ" in body
    assert "<@&423456789012345678>" in body
    assert "4 jours" in body


def test_history_view_is_private_and_paginates():
    view = MemberHistoryView(author_id=USER_ID, guild_id=GUILD_ID, target_id=USER_ID)
    assert view.author_id == USER_ID
    assert view.page == 0
    assert view.records == []


def test_premium_buttons_keep_target_snowflake_not_public_case_reference():
    action = PremiumLogAction("unban", GUILD_ID, USER_ID)
    assert action.item.style is discord.ButtonStyle.secondary
    assert str(USER_ID) in action.item.custom_id
    assert "BAN-" not in action.item.custom_id
