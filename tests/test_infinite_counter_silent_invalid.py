"""Compteur infini : avis clairs et réactions (06/11/2026).

Avant : tout message invalide était supprimé en silence. Demande du 06/11 :
réaction sur un bon nombre, croix + « ce n'est pas le bon nombre, le suivant
est X » sur une erreur, « non » sur du texte ; réactions réglables.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cogs import infinite_counter as ic
from cogs.infinite_counter import InfiniteCounter


def _row(*, next_number: int = 60, last_user_id: int | None = 999, react_ok=None, react_bad=None):
    return {
        "guild_id": 1, "channel_id": 10, "next_number": next_number, "last_user_id": last_user_id,
        "enabled": 1, "updated_at": 0, "react_ok": react_ok, "react_bad": react_bad,
    }


def _message(content: str, *, user_id: int = 7):
    return SimpleNamespace(
        author=SimpleNamespace(id=user_id, bot=False, mention=f"<@{user_id}>"),
        guild=SimpleNamespace(id=1),
        channel=SimpleNamespace(id=10, send=AsyncMock()),
        content=content,
        delete=AsyncMock(),
        add_reaction=AsyncMock(),
    )


def _cog(row):
    db = SimpleNamespace(fetchone=AsyncMock(side_effect=[row, row]), execute=AsyncMock())
    return InfiniteCounter(SimpleNamespace(db=db)), db


@pytest.mark.asyncio
async def test_wrong_number_gets_a_cross_the_next_number_then_is_cleaned(monkeypatch):
    monkeypatch.setattr(ic, "DUREE_AVIS", 0.01)
    cog, db = _cog(_row())
    message = _message("59")
    await cog.on_message(message)
    message.add_reaction.assert_awaited_once_with("❌")
    avis = message.channel.send.await_args.args[0]
    assert "ce n'est pas le bon nombre" in avis and "**60**" in avis
    assert message.channel.send.await_args.kwargs["allowed_mentions"].users is False
    db.execute.assert_not_awaited()
    await asyncio.sleep(0.05)
    message.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_text_message_is_deleted_with_a_no():
    cog, db = _cog(_row())
    message = _message("60 salut")
    await cog.on_message(message)
    message.delete.assert_awaited_once()
    assert message.channel.send.await_args.args[0].startswith("Non <@7>")
    message.add_reaction.assert_not_awaited()
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_same_member_cannot_count_twice(monkeypatch):
    monkeypatch.setattr(ic, "DUREE_AVIS", 0.01)
    cog, db = _cog(_row(last_user_id=7))
    message = _message("60", user_id=7)
    await cog.on_message(message)
    assert "deux fois de suite" in message.channel.send.await_args.args[0]
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_number_advances_and_gets_the_configured_reaction():
    cog, db = _cog(_row(last_user_id=999, react_ok="🔥"))
    message = _message("60", user_id=7)
    await cog.on_message(message)
    message.delete.assert_not_awaited()
    message.add_reaction.assert_awaited_once_with("🔥")
    query, params = db.execute.await_args.args
    assert "SET next_number=?,last_user_id=?,updated_at=?" in query
    assert params[0] == 61 and params[1] == 7


@pytest.mark.asyncio
async def test_wrong_number_uses_the_configured_error_reaction(monkeypatch):
    monkeypatch.setattr(ic, "DUREE_AVIS", 0.01)
    cog, _ = _cog(_row(react_bad="🚫"))
    message = _message("12")
    await cog.on_message(message)
    message.add_reaction.assert_awaited_once_with("🚫")
