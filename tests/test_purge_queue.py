"""Suppressions regroupées par salon (utils/purge_queue.py).

Sous une rafale de plusieurs spammeurs, chaque message partait dans son propre
appel DELETE : 83 appels et un délai médian de 5 s pour 20 spammeurs
(tools/spam_burst_e2e.py). La file regroupe ce qui attend pendant un appel.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, Mock

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from utils.purge_queue import SuppressionsGroupees  # noqa: E402


def _channel(channel_id: int = 55) -> Mock:
    channel = Mock(id=channel_id)
    channel.delete_messages = AsyncMock()
    return channel


def _message(channel: Mock, message_id: int) -> Mock:
    message = Mock(id=message_id, channel=channel)
    message.delete = AsyncMock()
    return message


def _http_error(cls, status: int):
    return cls(Mock(status=status, reason="x"), "erreur")


@pytest.mark.asyncio
async def test_un_message_seul_part_tout_de_suite_en_suppression_simple():
    queue = SuppressionsGroupees()
    channel = _channel()
    message = _message(channel, 1)
    assert await queue.supprimer(message) is True
    message.delete.assert_awaited_once()
    channel.delete_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_rafale_simultanee_part_en_un_seul_appel_groupe():
    queue = SuppressionsGroupees()
    channel = _channel()
    messages = [_message(channel, i) for i in range(30)]
    results = await asyncio.gather(*(queue.supprimer(m) for m in messages))
    assert all(results)
    channel.delete_messages.assert_awaited_once()
    assert len(channel.delete_messages.await_args.args[0]) == 30
    assert not any(m.delete.await_count for m in messages)


@pytest.mark.asyncio
async def test_ce_qui_arrive_pendant_un_appel_part_au_tour_suivant():
    queue = SuppressionsGroupees()
    channel = _channel()
    first = _message(channel, 1)
    gate = asyncio.Event()

    async def slow_delete(*_a, **_k):
        await gate.wait()

    first.delete.side_effect = slow_delete
    pending_first = asyncio.ensure_future(queue.supprimer(first))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    later = [_message(channel, i) for i in range(2, 8)]
    pending_later = [asyncio.ensure_future(queue.supprimer(m)) for m in later]
    await asyncio.sleep(0)
    gate.set()
    assert await pending_first is True
    assert all(await asyncio.gather(*pending_later))
    channel.delete_messages.assert_awaited_once()
    assert len(channel.delete_messages.await_args.args[0]) == 6


@pytest.mark.asyncio
async def test_plus_de_cent_messages_sont_decoupes_par_lots_de_cent():
    queue = SuppressionsGroupees()
    channel = _channel()
    messages = [_message(channel, i) for i in range(250)]
    assert all(await asyncio.gather(*(queue.supprimer(m) for m in messages)))
    sizes = [len(call.args[0]) for call in channel.delete_messages.await_args_list]
    assert sizes == [100, 100, 50]


@pytest.mark.asyncio
async def test_lot_refuse_repli_un_par_un_et_message_disparu_signale():
    queue = SuppressionsGroupees()
    channel = _channel()
    channel.delete_messages.side_effect = _http_error(discord.NotFound, 404)
    kept = _message(channel, 1)
    gone = _message(channel, 2)
    gone.delete.side_effect = _http_error(discord.NotFound, 404)
    results = await asyncio.gather(queue.supprimer(kept), queue.supprimer(gone))
    assert results == [True, False]
    kept.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_les_salons_sont_independants():
    queue = SuppressionsGroupees()
    a, b = _channel(1), _channel(2)
    messages = [_message(a, 1), _message(a, 2), _message(b, 3), _message(b, 4)]
    assert all(await asyncio.gather(*(queue.supprimer(m) for m in messages)))
    assert len(a.delete_messages.await_args.args[0]) == 2
    assert len(b.delete_messages.await_args.args[0]) == 2
