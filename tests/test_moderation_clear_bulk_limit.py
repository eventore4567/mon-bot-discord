"""Regression guards for +clear and /clear."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest

from cogs.moderation import Moderation

ROOT = Path(__file__).resolve().parents[1]


class _Message:
    def __init__(self, index: int):
        self.id = index
        self.created_at = discord.utils.utcnow()
        self.delete_calls = 0

    async def delete(self):
        self.delete_calls += 1


def _message(index: int):
    return _Message(index)


class _Channel:
    def __init__(self, *, reject_over_limit: bool = True):
        self.bulk_calls: list[int] = []
        self.reject_over_limit = reject_over_limit

    async def delete_messages(self, messages):
        messages = list(messages)
        if self.reject_over_limit and len(messages) > 100:
            raise discord.ClientException("Can only bulk delete messages up to 100 messages")
        self.bulk_calls.append(len(messages))


def test_purge_101_candidates_is_split_without_rereading_history():
    channel = _Channel()
    ctx = SimpleNamespace(channel=channel)
    candidates = [_message(i) for i in range(101)]

    deleted = asyncio.run(Moderation._purge_messages(ctx, candidates))

    assert channel.bulk_calls == [100]
    assert candidates[-1].delete_calls == 1
    assert len(deleted) == 101


def test_client_exception_falls_back_to_selected_messages_only():
    class _Broken(_Channel):
        async def delete_messages(self, messages):
            raise discord.ClientException("bulk delete refused")

    channel = _Broken()
    ctx = SimpleNamespace(channel=channel)
    candidates = [_message(i) for i in range(5)]

    deleted = asyncio.run(Moderation._purge_messages(ctx, candidates))

    assert [message.delete_calls for message in candidates] == [1, 1, 1, 1, 1]
    assert len(deleted) == 5


@pytest.mark.parametrize("count", [1, 2, 100])
def test_small_batches_keep_expected_delete_path(count):
    channel = _Channel()
    candidates = [_message(i) for i in range(count)]
    ctx = SimpleNamespace(channel=channel)

    asyncio.run(Moderation._purge_messages(ctx, candidates))

    if count == 1:
        assert candidates[0].delete_calls == 1
        assert channel.bulk_calls == []
    else:
        assert channel.bulk_calls == [count]
        assert all(message.delete_calls == 0 for message in candidates)


def test_clear_public_range_starts_at_two():
    source = (ROOT / "cogs" / "moderation.py").read_text(encoding="utf-8")
    assert 'nombre: commands.Range[int, 2, 100]' in source
    assert 'Nombre de messages à supprimer (2 à 100)' in source
    assert 'requested = max(2, min(int(nombre), 100))' in source


def test_clear_protects_the_slash_original_response_from_deletion():
    source = (ROOT / "cogs" / "moderation.py").read_text(encoding="utf-8")
    start = source.index('@commands.hybrid_command(name="clear"')
    end = source.index("    async def _log_clear_safely", start)
    body = source[start:end]

    assert "await ctx.interaction.original_response()" in body
    assert "protected_ids.add(int(original.id))" in body
    assert "if message_id in protected_ids:" in body
    assert "ctx.channel.purge(" not in body


def test_clear_plus_and_slash_share_exact_same_confirmation_text():
    source = (ROOT / "cogs" / "moderation.py").read_text(encoding="utf-8")
    start = source.index('@commands.hybrid_command(name="clear"')
    end = source.index("    @staticmethod\n    async def _purge_messages", start)
    body = source[start:end]

    assert 'texte = f"{len(messages)} message(s) supprimé(s)."' in body
    assert "await panels.texte_court(ctx.channel, texte" in body
    assert "await panels.texte_court(ctx, texte" in body


def test_clear_log_is_one_bulk_summary_with_exact_count():
    source = (ROOT / "cogs" / "moderation.py").read_text(encoding="utf-8")
    start = source.index("async def _send_clear_log")
    end = source.index('@commands.hybrid_command(name="slowmode"', start)
    block = source[start:end]

    assert '("Messages supprimés", str(len(messages)), True)' in block
    assert '("Salon", f"<#{ctx.channel.id}>", True)' in block
    assert '("Modérateur", f"<@{ctx.author.id}>", True)' in block
    assert '("Commande", f"`{command_name} {requested}`", True)' in block
    assert '"message_bulk"' in block
    assert 'log_service.send_log(' in block
