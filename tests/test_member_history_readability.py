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
async def test_four_events_render_as_separate_components_not_one_crammed_text():
    view = MemberHistoryView(
        author_id=42, guild_id=123456789012345678, target_id=987654321012345678,
    )
    counts = {"role_add": 1, "message_delete": 2, "member_warn": 1}
    with patch(
        "cogs.log_history_center.fetch_log_history_page",
        AsyncMock(return_value=(_events(4), 28, counts)),
    ):
        await view.render(_guild())
    assert len(view.children) == 3
    header, journal, navigation = view.children
    assert all(isinstance(x, discord.ui.Container) for x in view.children)
    assert isinstance(header.children[0], discord.ui.Section)
    items = journal.children
    assert len(items) == 9   # titre, séparation, 4 événements, 3 séparateurs
    texts = [x for x in items if isinstance(x, discord.ui.TextDisplay)]
    assert len(texts) == 5
    assert sum(isinstance(x, discord.ui.Separator) for x in items) == 4
    assert all("Événement" in t.content for t in texts[1:])
    assert len([
        item for item in navigation.children if isinstance(item, discord.ui.ActionRow)
    ]) == 4
    assert "Page 1/7" in navigation.children[0].content


@pytest.mark.asyncio
async def test_filter_selection_keeps_interactions_and_refreshes_journal():
    view = MemberHistoryView(
        author_id=42, guild_id=123456789012345678, target_id=987654321012345678,
    )
    backend = AsyncMock(return_value=(_events(4), 28, {}))
    with patch("cogs.log_history_center.fetch_log_history_page", backend):
        await view.render(_guild())
        # Le second filtre de la première rangée est celui des warns.
        nav = view.children[2]
        row = nav.children[1]
        button = row.children[1]
        interaction = SimpleNamespace(
            guild=_guild(),
            response=SimpleNamespace(edit_message=AsyncMock()),
        )
        await button.callback(interaction)
    assert view.filter == "warn"
    assert view.page == 0
    interaction.response.edit_message.assert_awaited_once()
    assert backend.call_count == 2


@pytest.mark.asyncio
async def test_empty_history_keeps_filters_and_private_selection():
    view = MemberHistoryView(
        author_id=42, guild_id=123456789012345678, target_id=987654321012345678,
    )
    with patch(
        "cogs.log_history_center.fetch_log_history_page",
        AsyncMock(return_value=([], 0, {})),
    ):
        await view.render(_guild(avatar=False))
    _, journal, navigation = view.children
    assert any("Aucun événement" in getattr(x, "content", "") for x in journal.children)
    assert len([x for x in navigation.children if isinstance(x, discord.ui.ActionRow)]) == 4
    assert len(view.children) == 3
