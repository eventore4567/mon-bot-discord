"""Dossier membre : lisibilité Components V2 et pagination préservée."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
import pytest

from cogs.log_history_center import (
    MemberHistoryView, _history_detail, _history_event_block, _history_member_header,
)


def _events(number=4):
    return [
        {
            "id": i + 1,
            "log_type": ["role_add", "message_delete", "message_delete", "member_warn"][i % 4],
            "title": "Événement",
            "description": (
                "Salon: <#123456789012345678> · " + chr(96) + "#・règle" + chr(96)
                + "\nContenu: message d'origine"
                if i in (1, 2) else "Rôle: <@&123456789012345678>\nMotif: Raison informative"
            ),
            "created_at": 1792517100 - i * 360,
            "moderator_id": 123456789012345678 if i == 0 else None,
        }
        for i in range(number)
    ]


def _guild(avatar=True):
    member = SimpleNamespace(
        display_name="Tomioka",
        display_avatar=SimpleNamespace(url="https://cdn.discordapp.com/avatars/123/avatar.png") if avatar else None,
    )
    return SimpleNamespace(get_member=lambda _: member)


def test_history_details_have_clear_labels_and_no_duplicate_channel():
    result = _history_detail(
        "Salon: <#123456789012345678> · " + chr(96) + "#・règle" + chr(96)
        + "\nContenu: Bonjour\nSupprimé par: Exécuteur inconnu"
    )
    assert "**Salon** · <#123456789012345678>" in result
    assert "#・règle" not in result
    assert "**Contenu**\n> Bonjour" in result
    assert "**Supprimé par** · Exécuteur inconnu" in result


def test_history_event_is_a_standalone_labeled_piece():
    result = _history_event_block(_events(1)[0], index=2)
    assert "Rôle ajouté" in result
    assert "Événement 02" in result
    assert "**Responsable** · <@" in result
    assert "**Motif** · Raison informative" in result


def test_history_header_uses_native_thumbnail_for_wide_layout():
    counts = {"warn": 1, "mute": 2, "ban": 3, "kick": 4}
    panel = _history_member_header(
        "Tomioka", counts, total=28, member=_guild().get_member(42),
    )
    assert isinstance(panel, discord.ui.Container)
    assert isinstance(panel.children[0], discord.ui.Section)
    assert isinstance(panel.children[1], discord.ui.Separator)
    assert "Vue d'ensemble des sanctions" in panel.children[2].content


@pytest.mark.asyncio
async def test_v4_layout_has_four_tabs_single_filter_and_expandable_event_rows():
    view = MemberHistoryView(
        author_id=42, guild_id=123456789012345678,
        target_id=987654321012345678,
    )
    data = _events(3)
    counts = {"role_add": 1, "message_delete": 2, "member_warn": 1}
    with patch(
        "cogs.log_history_center.fetch_log_history_page",
        AsyncMock(return_value=(data, 28, counts)),
    ):
        await view.render(_guild())
    assert len(view.children) == 3
    header, journal, nav = view.children
    assert all(isinstance(item, discord.ui.Container) for item in view.children)
    assert isinstance(header.children[0], discord.ui.Section)
    text_items = [item for item in journal.children if isinstance(item, discord.ui.TextDisplay)]
    assert len(text_items) == 4  # heading and three separate event cards
    assert sum(isinstance(item, discord.ui.Separator) for item in journal.children) == 3
    rows = [item for item in nav.children if isinstance(item, discord.ui.ActionRow)]
    assert len(rows) == 5  # tabs, filter, details, member selector, page navigation
    assert len(rows[0].children) == 4
    assert len(rows[2].children) == 3
    assert any("Page 1/10" in getattr(item, "content", "") for item in nav.children)


@pytest.mark.asyncio
async def test_dropdown_filter_and_detail_buttons_work_without_losing_pagination():
    view = MemberHistoryView(
        author_id=42, guild_id=123456789012345678,
        target_id=987654321012345678,
    )
    backend = AsyncMock(return_value=(_events(3), 6, {}))
    inter = SimpleNamespace(
        guild=_guild(), data={"values": ["voice"]},
        response=SimpleNamespace(edit_message=AsyncMock()),
    )
    with patch("cogs.log_history_center.fetch_log_history_page", backend):
        await view.render(_guild())
        select = view.children[2].children[1].children[0]
        await select.callback(inter)
        assert view.filter == "voice"
        assert backend.call_args.kwargs["event_types"] is not None
        # Voice is a tab too; now expand the first visible event.
        button = view.children[2].children[2].children[0]
        await button.callback(inter)
        assert view.expanded == 1
        assert "**Motif**" in view.children[1].children[2].content
        assert backend.call_count == 3
    assert inter.response.edit_message.await_count == 2


@pytest.mark.asyncio
async def test_vocal_and_sanctions_tabs_select_relevant_event_types():
    view = MemberHistoryView(
        author_id=42, guild_id=123456789012345678,
        target_id=987654321012345678,
    )
    backend = AsyncMock(return_value=(_events(2), 2, {}))
    interaction = SimpleNamespace(
        guild=_guild(), response=SimpleNamespace(edit_message=AsyncMock())
    )
    with patch("cogs.log_history_center.fetch_log_history_page", backend):
        await view.render(_guild())
        voice = view.children[2].children[0].children[1]
        await voice.callback(interaction)
        assert view.tab == "voice"
        assert "voice_join" in backend.call_args.kwargs["event_types"]
        sanction = view.children[2].children[0].children[2]
        await sanction.callback(interaction)
        assert view.tab == "sanctions"
        assert "member_warn" in backend.call_args.kwargs["event_types"]
    assert interaction.response.edit_message.await_count == 2


@pytest.mark.asyncio
async def test_settings_tab_can_be_opened_without_touching_member_sanctions():
    view = MemberHistoryView(
        author_id=42, guild_id=123456789012345678,
        target_id=987654321012345678,
    )
    backend = AsyncMock(return_value=([], 0, {}))
    inter = SimpleNamespace(
        guild=_guild(), response=SimpleNamespace(edit_message=AsyncMock())
    )
    with patch("cogs.log_history_center.fetch_log_history_page", backend):
        await view.render(_guild())
        await view.children[2].children[0].children[3].callback(inter)
    assert view.tab == "settings"
    assert len(view.children) == 3
    assert "Statut indisponible" in view.children[1].children[-1].content


@pytest.mark.asyncio
async def test_empty_history_keeps_filter_and_member_selection():
    view = MemberHistoryView(
        author_id=42, guild_id=123456789012345678,
        target_id=987654321012345678,
    )
    with patch(
        "cogs.log_history_center.fetch_log_history_page",
        AsyncMock(return_value=([], 0, {})),
    ):
        await view.render(_guild(avatar=False))
    _, journal, nav = view.children
    assert any("Aucun événement" in getattr(x, "content", "") for x in journal.children)
    assert len([x for x in nav.children if isinstance(x, discord.ui.ActionRow)]) == 4
    assert len(view.children) == 3
