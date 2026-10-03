from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cogs.infinite_counter import InfiniteCounter


def _row(*, next_number: int = 60, last_user_id: int | None = 999):
    return {
        "guild_id": 1,
        "channel_id": 10,
        "next_number": next_number,
        "last_user_id": last_user_id,
        "enabled": 1,
        "updated_at": 0,
    }


def _message(content: str, *, user_id: int = 7):
    return SimpleNamespace(
        author=SimpleNamespace(id=user_id, bot=False),
        guild=SimpleNamespace(id=1),
        channel=SimpleNamespace(id=10),
        content=content,
        delete=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_wrong_number_is_deleted_without_sending_anything():
    db = SimpleNamespace(
        fetchone=AsyncMock(side_effect=[_row(), _row()]),
        execute=AsyncMock(),
    )
    cog = InfiniteCounter(SimpleNamespace(db=db))
    message = _message("59")

    await cog.on_message(message)

    message.delete.assert_awaited_once()
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_text_message_is_deleted_without_sending_anything():
    db = SimpleNamespace(
        fetchone=AsyncMock(side_effect=[_row(), _row()]),
        execute=AsyncMock(),
    )
    cog = InfiniteCounter(SimpleNamespace(db=db))
    message = _message("60 salut")

    await cog.on_message(message)

    message.delete.assert_awaited_once()
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_same_member_cannot_count_twice_and_message_is_only_deleted():
    db = SimpleNamespace(
        fetchone=AsyncMock(side_effect=[_row(last_user_id=7), _row(last_user_id=7)]),
        execute=AsyncMock(),
    )
    cog = InfiniteCounter(SimpleNamespace(db=db))
    message = _message("60", user_id=7)

    await cog.on_message(message)

    message.delete.assert_awaited_once()
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_number_still_advances_counter_without_deleting_message():
    db = SimpleNamespace(
        fetchone=AsyncMock(side_effect=[_row(last_user_id=999), _row(last_user_id=999)]),
        execute=AsyncMock(),
    )
    cog = InfiniteCounter(SimpleNamespace(db=db))
    message = _message("60", user_id=7)

    await cog.on_message(message)

    message.delete.assert_not_awaited()
    db.execute.assert_awaited_once()
    query, params = db.execute.await_args.args
    assert "SET next_number=?,last_user_id=?,updated_at=?" in query
    assert params[0] == 61
    assert params[1] == 7
