"""Régression : une seule réponse IA passive par message Discord."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from cogs import passive_ai_single_reply_final as guard


class FakePool:
    def __init__(self):
        self.claims: set[tuple[str, int]] = set()
        self.created = False

    async def execute(self, sql, *args):
        if "CREATE TABLE" in sql:
            self.created = True
        return "OK"

    async def fetchrow(self, sql, *args):
        instance_key, message_id = str(args[0]), int(args[1])
        key = (instance_key, message_id)
        if key in self.claims:
            return None
        self.claims.add(key)
        return {"message_id": message_id}


def test_primary_service_identity(monkeypatch):
    monkeypatch.setenv("RAILWAY_SERVICE_ID", guard.PRIMARY_RAILWAY_SERVICE_ID)
    monkeypatch.setenv("RAILWAY_SERVICE_NAME", "mon-bot-discord")
    assert guard._is_primary_service() is True


def test_secondary_service_identity(monkeypatch):
    monkeypatch.setenv("RAILWAY_SERVICE_ID", "237537af-2be4-40fa-8527-301358d533a9")
    monkeypatch.setenv("RAILWAY_SERVICE_NAME", "[+] Bot'Odboug |")
    assert guard._is_primary_service() is False


def test_same_message_id_is_claimed_once_locally():
    guard._RECENT_MESSAGE_IDS.clear()
    message = SimpleNamespace(id=123456789012345678)
    assert guard._claim_message(message) is True
    assert guard._claim_message(message) is False


def test_different_message_ids_are_never_rate_limited_locally():
    guard._RECENT_MESSAGE_IDS.clear()
    first = SimpleNamespace(id=123456789012345678)
    second = SimpleNamespace(id=123456789012345679)
    assert guard._claim_message(first) is True
    assert guard._claim_message(second) is True


def test_same_message_id_has_one_global_postgres_winner():
    guard._TABLE_READY_POOLS.clear()
    pool = FakePool()
    bot = SimpleNamespace(
        sentrix_durable_store=SimpleNamespace(pool=pool, instance_key="sentrix")
    )
    message = SimpleNamespace(id=123456789012345678)

    first = asyncio.run(guard._claim_shared(bot, message))
    second = asyncio.run(guard._claim_shared(bot, message))

    assert first == (True, "postgres")
    assert second == (False, "postgres")
    assert pool.created is True


def test_different_message_ids_both_win_postgres_immediately():
    guard._TABLE_READY_POOLS.clear()
    pool = FakePool()
    bot = SimpleNamespace(
        sentrix_durable_store=SimpleNamespace(pool=pool, instance_key="sentrix")
    )

    first = asyncio.run(
        guard._claim_shared(bot, SimpleNamespace(id=123456789012345678))
    )
    second = asyncio.run(
        guard._claim_shared(bot, SimpleNamespace(id=123456789012345679))
    )

    assert first == (True, "postgres")
    assert second == (True, "postgres")


def test_ai_listener_detection_only_targets_cogs_ai():
    async def unrelated(message):
        return message

    unrelated.__module__ = "cogs.logs"
    unrelated.__name__ = "on_message"
    assert guard._is_ai_on_message(unrelated) is False

    async def ai_listener(message):
        return message

    ai_listener.__module__ = "cogs.ai"
    ai_listener.__name__ = "on_message"
    assert guard._is_ai_on_message(ai_listener) is True
