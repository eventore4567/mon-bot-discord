"""Régressions du registre partagé anti-doublon IA."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from utils import ai_reply_claim as claims


def setup_function():
    claims.reset_for_tests()


def test_one_local_winner_for_same_message():
    message = SimpleNamespace(id=1001)
    assert claims.claim(message, "primary") is True
    assert claims.claim(message, "backup") is False


def test_different_messages_are_independent():
    assert claims.claim(1001, "primary") is True
    assert claims.claim(1002, "backup") is True


def test_same_owner_is_idempotent():
    assert claims.claim(1001, "primary") is True
    assert claims.claim(1001, "primary") is True


def test_terminal_blocks_every_future_owner():
    assert claims.claim(1001, "primary") is True
    assert claims.complete(1001, "primary") is True
    assert claims.claim(1001, "backup") is False
    assert claims.state(1001) == "terminal"


def test_release_allows_backup_takeover():
    assert claims.claim(1001, "primary") is True
    assert claims.release(1001, "primary") is True
    assert claims.claim(1001, "backup") is True


def test_wrong_owner_cannot_release_or_complete():
    assert claims.claim(1001, "primary") is True
    assert claims.release(1001, "backup") is False
    assert claims.complete(1001, "backup") is False
    assert claims.state(1001) == "claimed"


def test_slow_primary_never_gets_stolen_by_backup():
    async def scenario():
        assert claims.claim(1001, "primary") is True
        backup = asyncio.create_task(
            claims.wait_and_claim(1001, "backup", primary_grace=0.0)
        )
        await asyncio.sleep(0.08)
        assert backup.done() is False
        assert claims.complete(1001, "primary") is True
        assert await asyncio.wait_for(backup, timeout=1) is False

    asyncio.run(scenario())


def test_backup_resumes_after_primary_failure():
    async def scenario():
        assert claims.claim(1001, "primary") is True
        backup = asyncio.create_task(
            claims.wait_and_claim(1001, "backup", primary_grace=0.0)
        )
        await asyncio.sleep(0.03)
        assert claims.release(1001, "primary") is True
        assert await asyncio.wait_for(backup, timeout=1) is True
        assert claims.complete(1001, "backup") is True
        assert claims.state(1001) == "terminal"

    asyncio.run(scenario())


def test_primary_grace_prevents_backup_from_winning_scheduler_race():
    async def scenario():
        backup = asyncio.create_task(
            claims.wait_and_claim(1001, "backup", primary_grace=0.08)
        )
        await asyncio.sleep(0.01)
        assert claims.claim(1001, "primary") is True
        await asyncio.sleep(0.03)
        assert backup.done() is False
        claims.complete(1001, "primary")
        assert await asyncio.wait_for(backup, timeout=1) is False

    asyncio.run(scenario())


def test_two_hundred_concurrent_attempts_have_one_winner():
    async def scenario():
        async def contender(index: int):
            # Aucun await avant claim : exactement le contrat utilisé en production.
            return claims.claim(1001, f"owner-{index}")

        results = await asyncio.gather(*(contender(i) for i in range(200)))
        assert sum(bool(value) for value in results) == 1

    asyncio.run(scenario())


def test_no_postgres_pool_keeps_local_path_available():
    bot = SimpleNamespace(sentrix_durable_store=SimpleNamespace(pool=None, instance_key="sentrix"))
    allowed, mode = asyncio.run(
        claims.acquire_distributed(bot, 1001, "primary", wait=False)
    )
    assert allowed is True
    assert mode == "local-only"
