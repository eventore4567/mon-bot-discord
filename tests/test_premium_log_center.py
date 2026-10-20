"""Contrats du journal premium SentriX, indépendants de l'API Discord."""
import asyncio
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


def test_compact_voice_log_shows_small_avatar_only_and_no_repeated_mention():
    embed = discord.Embed(title="Entrée en vocal")
    embed.add_field(name="Membre", value=f"<@{USER_ID}>")
    embed.add_field(name="Salon", value="<#323456789012345678>")
    view = WideLogView(
        embed,
        "legacy-banner.webp",  # Ancienne valeur ignorée, même si encore fournie.
        identity_id=USER_ID,
        identity_name="moussa",
        identity_icon="https://cdn.discordapp.com/embed/avatars/0.png",
        log_type="voice_join",
    )
    items = list(_walk(view))
    assert any(isinstance(item, discord.ui.Section) for item in items)
    assert not any(isinstance(item, discord.ui.MediaGallery) for item in items)
    content = "\n".join(str(getattr(item, "content", "")) for item in items)
    assert content.count(f"<@{USER_ID}>") == 1
    assert "A rejoint" in content
    assert "\n> " not in content
    assert "legacy-banner.webp" not in content


def test_transport_does_not_upload_decorative_banner():
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


def test_premium_log_has_persistent_history_and_unban_buttons_without_reference():
    view = WideLogView(
        _embed(), "sentrix_premium_error.webp",
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
    assert action.item.style is discord.ButtonStyle.success
    assert str(USER_ID) in action.item.custom_id
    assert "BAN-" not in action.item.custom_id
