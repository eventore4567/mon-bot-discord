"""`+clear 100` : 101 candidats (100 + le message de commande) doivent être supprimés
par lots de 100 — discord.py refuse plus de 100 messages par appel groupé et lève
ClientException, qui n'est PAS une HTTPException (origine de SXR-CMD-0001)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import discord
import pytest

from cogs.moderation import Moderation


def _message(index: int):
    return SimpleNamespace(id=index, created_at=discord.utils.utcnow())


class _Channel:
    def __init__(self, *, reject_over_limit: bool = True):
        self.bulk_calls: list[int] = []
        self.purge_calls: list[int] = []
        self.reject_over_limit = reject_over_limit

    async def delete_messages(self, messages):
        messages = list(messages)
        if self.reject_over_limit and len(messages) > 100:
            raise discord.ClientException("Can only bulk delete messages up to 100 messages")
        self.bulk_calls.append(len(messages))

    async def purge(self, *, limit):
        self.purge_calls.append(limit)
        return [_message(i) for i in range(limit)]


def test_purge_101_candidates_is_split_in_chunks_of_100():
    channel = _Channel()
    ctx = SimpleNamespace(channel=channel)
    candidates = [_message(i) for i in range(101)]

    deleted = asyncio.run(Moderation._purge_messages(ctx, candidates, 101))

    assert channel.bulk_calls == [100, 1]
    assert channel.purge_calls == []
    assert len(deleted) == 101


def test_client_exception_falls_back_to_purge_instead_of_crashing():
    class _Broken(_Channel):
        async def delete_messages(self, messages):
            raise discord.ClientException("bulk delete refused")

    channel = _Broken()
    ctx = SimpleNamespace(channel=channel)
    candidates = [_message(i) for i in range(5)]

    deleted = asyncio.run(Moderation._purge_messages(ctx, candidates, 5))

    assert channel.purge_calls == [5]
    assert len(deleted) == 5


@pytest.mark.parametrize("count", [1, 2, 100])
def test_small_batches_keep_single_bulk_call(count):
    channel = _Channel()
    single_deleted = []

    async def _delete():
        single_deleted.append(True)

    candidates = [_message(i) for i in range(count)]
    for message in candidates:
        message.delete = _delete
    ctx = SimpleNamespace(channel=channel)

    asyncio.run(Moderation._purge_messages(ctx, candidates, count))

    if count == 1:
        assert single_deleted == [True]
        assert channel.bulk_calls == []
    else:
        assert channel.bulk_calls == [count]



def test_clear_public_range_starts_at_two():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "cogs" / "moderation.py").read_text(encoding="utf-8")
    assert 'nombre: commands.Range[int, 2, 100]' in source
    assert 'Nombre de messages à supprimer (2 à 100)' in source
    assert 'requested = max(2, min(int(nombre), 100))' in source



def test_clear_plus_and_slash_share_exact_same_confirmation_text():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "cogs" / "moderation.py").read_text(encoding="utf-8")

    start = source.index('@commands.hybrid_command(name="clear"')
    end = source.index("    @staticmethod\n    async def _purge_messages", start)
    body = source[start:end]

    # Une seule phrase est calculée avant la branche + / slash, puis réutilisée dans
    # les deux transports. Donc /clear 2 affiche bien le même « 2 message(s) supprimé(s). ».
    assert 'texte = f"{len(messages)} message(s) supprimé(s)."' in body
    assert "await panels.texte_court(ctx.channel, texte" in body
    assert "await panels.texte_court(ctx, texte" in body
