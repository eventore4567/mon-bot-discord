"""SentriX member dossier V5: native Discord markdown, user resolution and privacy."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
import pytest

from cogs.log_history_center import (
    MemberHistoryView, _history_detail, _history_brief,
    _history_event_block, _history_event_panel,
    _history_member_header, _member_display_name,
)


def _events(number=3):
    keys = ("role_add", "message_delete", "member_leave")
    return [
        {
            "id": i + 1, "log_type": keys[i % len(keys)],
            "title": "Événement",
            "description": [
                "Rôle: <@&123456789012345678>\nMotif: Attribution de rôle",
                "Salon: <#123456789012345678> · " + chr(96) + "#・règle" + chr(96)
                + "\nContenu: Bonjour",
                "Rôles avant le départ: <@&123456789012345678>\nPrésence: 301 jours",
            ][i % len(keys)],
            "created_at": 1792517100 - i * 360,
            "moderator_id": 123456789012345678 if i == 0 else None,
        }
        for i in range(number)
    ]


def _guild(*, user=True, avatar=True):
    profile = SimpleNamespace(
        id=987654321012345678, display_name="Tomioka", name="tomioka",
        display_avatar=(
            SimpleNamespace(url="https://cdn.discordapp.com/avatars/123/avatar.png")
            if avatar else None
        ),
    )
    return SimpleNamespace(get_member=lambda _: profile if user else None)


def _view(bot=None):
    return MemberHistoryView(
        author_id=42, guild_id=123456789012345678,
        target_id=987654321012345678, bot=bot,
    )


def _mock_history(data=None, total=28):
    return patch(
        "cogs.log_history_center.fetch_log_history_page",
        AsyncMock(return_value=(
            _events(2) if data is None else data,
            total,
            {"role_add": 1, "message_delete": 1, "member_leave": 1},
        )),
    )


def test_history_structured_details_are_small_native_discord_markdown():
    output = _history_detail(
        "Salon: <#123456789012345678> · " + chr(96) + "#・règle" + chr(96)
        + "\nContenu: Bonjour\nPrésence: 301 jours"
    )
    assert "**Salon** · <#123456789012345678>" in output
    assert "#・règle" not in output
    assert "**Contenu**\n> Bonjour" in output
    assert "**Présence sur le serveur** · 301 jours" in output
    assert "**Salon**" in _history_brief(_events(3)[1])
    assert "Événement 02" in _history_event_block(_events(2)[0], index=2)


def test_header_shows_real_user_mention_and_compact_id():
    member = _guild().get_member(2)
    panel = _history_member_header(
        "Tomioka", {"warn": 0, "mute": 0, "ban": 0, "kick": 0},
        total=28, member=member, target_id=987654321012345678,
    )
    assert isinstance(panel.children[0], discord.ui.Section)
    title = panel.children[0].children[0].content
    assert "**Tomioka**" in title
    assert "<@987654321012345678>" in title
    assert "ID : " + chr(96) + "987654321012345678" + chr(96) in title
    assert "Vue d'ensemble" not in title
    assert "Modération · Récapitulatif" in panel.children[2].content


def test_member_names_are_markdown_escaped():
    user = SimpleNamespace(display_name="**quelqu'un**", global_name=None, name="x")
    assert "**quelqu'un**" not in _member_display_name(user, 1)


@pytest.mark.asyncio
async def test_member_who_left_guild_gets_real_discord_username_from_api_once():
    user = SimpleNamespace(
        id=987654321012345678, global_name="Tomioka",
        display_avatar=SimpleNamespace(url="https://cdn.discordapp.com/avatars/123/profile.png"),
    )
    bot = SimpleNamespace(
        get_user=lambda _: None,
        fetch_user=AsyncMock(return_value=user),
    )
    view = _view(bot)
    guild = _guild(user=False)
    with _mock_history(data=[], total=0):
        await view.render(guild)
        await view.render(guild)
    assert bot.fetch_user.await_count == 1
    header = view.children[0].children[0].children[0].content
    assert "**Tomioka**" in header
    assert "<@987654321012345678>" in header
    assert "ID : " in header


@pytest.mark.asyncio
async def test_unresolvable_member_keeps_mention_and_id_not_raw_id_as_title():
    bot = SimpleNamespace(
        get_user=lambda _: None,
        fetch_user=AsyncMock(side_effect=discord.NotFound(
            SimpleNamespace(status=404, reason="Not Found"), "Unknown User"
        )),
    )
    view = _view(bot)
    with _mock_history(data=[], total=0):
        await view.render(_guild(user=False))
    header = view.children[0].children[0].content
    assert "Utilisateur Discord" in header
    assert "<@987654321012345678>" in header


@pytest.mark.asyncio
async def test_two_events_have_separate_wide_cards_with_detail_buttons():
    view = _view()
    with _mock_history():
        await view.render(_guild())
    assert len(view.children) == 5  # profile + journal heading + 2 records + controls
    profile, introduction, *cards, navigation = view.children
    assert isinstance(profile.children[0], discord.ui.Section)
    assert all(isinstance(x, discord.ui.Container) for x in view.children)
    assert len(cards) == 2
    assert len({id(card) for card in cards}) == 3
    for card in cards:
        assert isinstance(card.children[0], discord.ui.TextDisplay)
        assert isinstance(card.children[1], discord.ui.Separator)
        assert isinstance(card.children[2], discord.ui.TextDisplay)
        assert isinstance(card.children[3], discord.ui.ActionRow)
        assert card.children[3].children[0].label == "Voir les détails"
        assert "-# <t:" in card.children[0].content
    rows = [x for x in navigation.children if isinstance(x, discord.ui.ActionRow)]
    assert len(rows) == 4
    assert len(rows[0].children) == 4  # Tabs
    assert len(rows[1].children) == 1  # Dropdown
    assert len(rows[2].children) == 1  # MemberSelect
    assert len(rows[3].children) == 2  # Prev / Next
    assert any("Page 1/14" in getattr(x, "content", "") for x in navigation.children)


@pytest.mark.asyncio
async def test_expand_button_exposes_details_in_its_own_card():
    view = _view()
    backend = AsyncMock(return_value=(_events(2), 6, {}))
    guild = _guild()
    inter = SimpleNamespace(
        guild=guild, response=SimpleNamespace(edit_message=AsyncMock()),
    )
    with patch("cogs.log_history_center.fetch_log_history_page", backend):
        await view.render(guild)
        btn = view.children[2].children[3].children[0]
        await btn.callback(inter)
        assert view.expanded == 1
        assert "**Motif** · Attribution de rôle" in view.children[2].children[2].content
        assert view.children[2].children[3].children[0].label == "Masquer les détails"
        await view.children[2].children[3].children[0].callback(inter)
    assert view.expanded is None
    assert backend.call_count == 3


@pytest.mark.asyncio
async def test_dropdown_filters_and_voice_tabs_keep_all_categories():
    view = _view()
    backend = AsyncMock(return_value=(_events(2), 6, {}))
    inter = SimpleNamespace(
        guild=_guild(), data={"values": ["voice"]},
        response=SimpleNamespace(edit_message=AsyncMock()),
    )
    with patch("cogs.log_history_center.fetch_log_history_page", backend):
        await view.render(_guild())
        navigation = view.children[-1]
        select = navigation.children[1].children[0]
        await select.callback(inter)
        assert view.filter == "voice"
        assert "voice_join" in backend.call_args.kwargs["event_types"]
        voice = view.children[-1].children[0].children[1]
        await voice.callback(inter)
        assert view.tab == "voice"
        sanctions = view.children[-1].children[0].children[2]
        await sanctions.callback(inter)
        assert view.tab == "sanctions"
        assert "member_warn" in backend.call_args.kwargs["event_types"]
    assert inter.response.edit_message.await_count == 3


@pytest.mark.asyncio
async def test_empty_dossier_keeps_private_filters_and_member_selection():
    view = _view()
    with _mock_history(data=[], total=0):
        await view.render(_guild(avatar=False))
    assert len(view.children) == 3
    _, journal, navigation = view.children
    assert any("Aucun événement" in getattr(x, "content", "") for x in journal.children)
    assert len([x for x in navigation.children if isinstance(x, discord.ui.ActionRow)]) == 4
