from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest

from utils import onboarding_recovery as recovery


class DB:
    def __init__(self, conn):
        self.conn = conn

    async def execute(self, sql, params=()):
        await self.conn.execute(sql, params)
        await self.conn.commit()

    async def fetchone(self, sql, params=()):
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()


def member(guild, uid, joined, bot=False):
    return SimpleNamespace(id=uid, guild=guild, bot=bot, joined_at=datetime.fromtimestamp(joined, timezone.utc))


@pytest.mark.asyncio
async def test_recovery_only_replays_gap_and_survives_restart():
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        db = DB(conn)
        guild = SimpleNamespace(id=1)
        members = [member(guild, 1, 90), member(guild, 2, 110), member(guild, 3, 120, True)]
        async def fetch_members(limit):
            for m in members:
                yield m
        guild.fetch_members = fetch_members
        bot = SimpleNamespace(db=db, guilds=[guild], is_ready=lambda: True)
        handle = AsyncMock(return_value=True)
        runtime = recovery.Recovery(bot, handle, lambda: True)
        with patch.object(recovery.time, "time", return_value=100):
            await runtime.tick()
        handle.assert_not_awaited()  # Aucun ancien membre au premier démarrage.
        runtime = recovery.Recovery(bot, handle, lambda: True)
        with patch.object(recovery.time, "time", return_value=130):
            await runtime.tick()
            await runtime.tick()
        handle.assert_awaited_once_with(members[1])
        assert (await db.fetchone("SELECT online_at FROM onboarding_heartbeat WHERE guild_id=1"))["online_at"] == 130


@pytest.mark.asyncio
async def test_failed_recovery_keeps_checkpoint_for_retry_and_skips_standby():
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        db = DB(conn)
        await recovery.ensure_schema(db)
        await db.execute("INSERT INTO onboarding_heartbeat VALUES (1,100)")
        guild = SimpleNamespace(id=1)
        newcomer = member(guild, 1, 110)
        async def fetch_members(limit):
            yield newcomer
        guild.fetch_members = fetch_members
        handle = AsyncMock(side_effect=[False, True])
        bot = SimpleNamespace(db=db, guilds=[guild], is_ready=lambda: True)
        runtime = recovery.Recovery(bot, handle, lambda: False)
        await runtime.tick()
        handle.assert_not_awaited()
        runtime.is_active = lambda: True
        with patch.object(recovery.time, "time", return_value=130):
            await runtime.tick()
            assert (await db.fetchone("SELECT online_at FROM onboarding_heartbeat WHERE guild_id=1"))["online_at"] == 100
            await runtime.tick()
        assert handle.await_count == 2
        assert (await db.fetchone("SELECT online_at FROM onboarding_heartbeat WHERE guild_id=1"))["online_at"] == 130


@pytest.mark.asyncio
async def test_welcome_marker_is_persistent_but_allows_real_rejoin():
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        db = DB(conn)
        await recovery.ensure_schema(db)
        newcomer = member(SimpleNamespace(id=1), 2, 100)
        assert not await recovery.welcomed(db, newcomer)
        await recovery.mark_welcomed(db, newcomer)
        assert await recovery.welcomed(db, newcomer)
        newcomer.joined_at = datetime.fromtimestamp(200, timezone.utc)
        assert not await recovery.welcomed(db, newcomer)


@pytest.mark.asyncio
async def test_cannot_advance_checkpoint_when_member_listing_fails():
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        db = DB(conn)
        await recovery.ensure_schema(db)
        await db.execute("INSERT INTO onboarding_heartbeat VALUES (1,100)")
        async def fetch_members(limit):
            raise RuntimeError("Members intent unavailable")
            yield  # async iterator
        guild = SimpleNamespace(id=1, fetch_members=fetch_members)
        runtime = recovery.Recovery(SimpleNamespace(db=db, guilds=[guild], is_ready=lambda: True), AsyncMock(), lambda: True)
        await runtime.tick()
        assert (await db.fetchone("SELECT online_at FROM onboarding_heartbeat WHERE guild_id=1"))["online_at"] == 100
        assert runtime.pending == {1}


@pytest.mark.asyncio
async def test_bot_welcome_and_autorole_exit_before_database_or_discord():
    from cogs import setup_v2_completion
    from utils import welcome_autoroles
    bot = SimpleNamespace(db=SimpleNamespace(get_guild_config=AsyncMock()))
    newcomer = SimpleNamespace(bot=True)
    ok, _ = await setup_v2_completion._send_welcome(bot, newcomer)
    assert not ok
    assert await welcome_autoroles.apply(bot, newcomer) == ([], [])
    bot.db.get_guild_config.assert_not_awaited()
