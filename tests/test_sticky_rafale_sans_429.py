"""04/11/2026 : une rafale de messages ne republie le sticky qu'une seule fois.

En production, chaque message relisait (GET), supprimait puis republiait le
sticky : plus de 10 000 réponses 429 de Discord pendant un test de spam.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import sentrix_plus  # noqa: E402
from cogs.sentrix_plus import SentriXPlus  # noqa: E402

CHANNEL_ID = 4242


class _Db:
    def __init__(self):
        self.row = {"content": "Lisez le règlement", "message_id": 900, "every_messages": 1, "counter": 0}

    async def fetchone(self, sql, params):
        return dict(self.row) if self.row else None

    async def execute(self, sql, params):
        if "SET message_id=?,counter=0" in sql:
            self.row["message_id"], self.row["counter"] = params[0], 0
        elif "SET counter=?" in sql:
            self.row["counter"] = params[0]


class _Channel:
    id = CHANNEL_ID

    def __init__(self):
        self.envois = 0
        self.suppressions = []
        self.lectures = 0

    async def fetch_message(self, message_id):  # ne doit plus être appelé
        self.lectures += 1
        raise AssertionError("le sticky ne doit plus relire le message")

    def get_partial_message(self, message_id):
        canal = self

        class _Partiel:
            async def delete(self):
                canal.suppressions.append(message_id)

        return _Partiel()

    async def send(self, **kwargs):
        self.envois += 1
        return SimpleNamespace(id=1000 + self.envois)


def _message(channel, numero):
    return SimpleNamespace(
        id=5000 + numero,
        guild=SimpleNamespace(id=1),
        author=SimpleNamespace(bot=False),
        channel=channel,
    )


def test_une_rafale_ne_republie_le_sticky_qu_une_fois(monkeypatch):
    monkeypatch.setattr(sentrix_plus, "STICKY_REPOST_DELAY_SECONDS", 0.05)
    db = _Db()
    cog = SentriXPlus.__new__(SentriXPlus)
    cog.bot = SimpleNamespace(db=db)
    cog._no_sticky = {}
    cog._sticky_locks = {}
    cog._sticky_pending = {}
    channel = _Channel()

    async def scenario():
        for numero in range(30):
            await SentriXPlus.on_message(cog, _message(channel, numero))
        await asyncio.sleep(0.2)

    asyncio.run(scenario())
    assert channel.envois == 1
    assert channel.suppressions == [900]
    assert channel.lectures == 0
    assert db.row["message_id"] == 1001 and db.row["counter"] == 0
    assert cog._sticky_pending == {}


def test_un_spam_continu_republie_au_plus_une_fois_par_intervalle(monkeypatch):
    # Un salon toujours actif garde son sticky visible, sans un appel par message.
    monkeypatch.setattr(sentrix_plus, "STICKY_REPOST_DELAY_SECONDS", 0.05)
    db = _Db()
    cog = SentriXPlus.__new__(SentriXPlus)
    cog.bot = SimpleNamespace(db=db)
    cog._no_sticky = {}
    cog._sticky_locks = {}
    cog._sticky_pending = {}
    channel = _Channel()

    async def scenario():
        for numero in range(40):  # ~0,4 s de spam sans pause
            await SentriXPlus.on_message(cog, _message(channel, numero))
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.2)

    asyncio.run(scenario())
    assert 2 <= channel.envois <= 10
    assert channel.envois < 40
