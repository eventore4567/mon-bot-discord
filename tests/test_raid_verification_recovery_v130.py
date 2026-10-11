"""Sécurité : restauration du niveau de vérification après un raid rapide."""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils.raid_verification_recovery import (
    RAID_VERIFICATION_HOLD_SECONDS,
    RaidVerificationRecovery,
)


class MemoryDatabase:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

    async def execute(self, query, params=()):
        cursor = self.conn.execute(query, params)
        self.conn.commit()
        return cursor

    async def fetchone(self, query, params=()):
        return self.conn.execute(query, params).fetchone()

    async def fetchall(self, query, params=()):
        return self.conn.execute(query, params).fetchall()


class FakeGuild:
    def __init__(self, *, guild_id=1, original=discord.VerificationLevel.medium):
        self.id = guild_id
        self.verification_level = original
        self.me = SimpleNamespace(
            guild_permissions=SimpleNamespace(view_audit_log=True)
        )
        self.edits = []
        self.audit_entries = []
        self.edit_exception = None

    async def edit(self, *, verification_level, reason):
        if self.edit_exception is not None:
            raise self.edit_exception
        old = self.verification_level
        self.verification_level = verification_level
        self.edits.append((old, verification_level, reason))
        self.audit_entries.insert(
            0,
            SimpleNamespace(
                created_at=datetime.now(timezone.utc),
                user=SimpleNamespace(id=444),
                before=SimpleNamespace(verification_level=old),
                after=SimpleNamespace(verification_level=verification_level),
            ),
        )

    async def audit_logs(self, *, limit, action, after):
        assert action is discord.AuditLogAction.guild_update
        for entry in self.audit_entries[:limit]:
            if entry.created_at > after:
                yield entry


def make_recovery(guild=None, db=None):
    db = db or MemoryDatabase()
    guild = guild or FakeGuild()
    bot = SimpleNamespace(
        db=db,
        user=SimpleNamespace(id=444),
        get_guild=lambda guild_id: guild if guild_id == guild.id else None,
    )
    return RaidVerificationRecovery(bot), guild, db


@pytest.mark.asyncio
async def test_raid_raise_and_restore_previous_level_after_quiet_period():
    guard, guild, _ = make_recovery()
    now = int(time.time())
    assert await guard.protect(guild, now=now) is True
    assert guild.verification_level == discord.VerificationLevel.highest
    assert await guard.restore_due(now=now + RAID_VERIFICATION_HOLD_SECONDS - 1) == {
        "restored": 0, "cancelled": 0, "deferred": 0
    }
    result = await guard.restore_due(now=now + RAID_VERIFICATION_HOLD_SECONDS + 1)
    assert result["restored"] == 1
    assert guild.verification_level == discord.VerificationLevel.medium
    assert len(guild.edits) == 2


@pytest.mark.asyncio
async def test_raid_raise_persists_across_manager_restart_and_extends_on_second_wave():
    guard, guild, db = make_recovery()
    now = int(time.time())
    await guard.protect(guild, now=now)
    assert await guard.protect(guild, now=now + 600) is False
    second, _, _ = make_recovery(guild, db=db)
    assert (await second.restore_due(now=now + 900))["restored"] == 0
    assert (await second.restore_due(now=now + 1501))["restored"] == 1
    assert guild.verification_level == discord.VerificationLevel.medium


@pytest.mark.asyncio
async def test_manually_changed_level_cancels_automatic_restore():
    guard, guild, db = make_recovery()
    now = int(time.time())
    await guard.protect(guild, now=now)
    # Le Gateway nous avertit du changement initial fait par notre bot.
    before = SimpleNamespace(verification_level=discord.VerificationLevel.medium)
    await guard.on_guild_level_change(before, guild)
    # Puis le propriétaire choisit HIGH, et ensuite MAXIMUM.
    before = SimpleNamespace(verification_level=discord.VerificationLevel.highest)
    guild.verification_level = discord.VerificationLevel.high
    await guard.on_guild_level_change(before, guild)
    guild.verification_level = discord.VerificationLevel.highest
    assert (await guard.restore_due(now=now + 901))["restored"] == 0
    assert len(guild.edits) == 1
    assert await db.fetchone(
        "SELECT * FROM sentrix_raid_verification_restore WHERE guild_id = ?", (guild.id,)
    ) is None


@pytest.mark.asyncio
async def test_raid_restoration_refuses_audit_log_access_without_changing_server():
    guard, guild, _ = make_recovery()
    now = int(time.time())
    await guard.protect(guild, now=now)
    guild.me.guild_permissions.view_audit_log = False
    result = await guard.restore_due(now=now + 1000)
    assert result["deferred"] == 1
    assert len(guild.edits) == 1
    assert guild.verification_level == discord.VerificationLevel.highest


@pytest.mark.asyncio
async def test_raid_restoration_refuses_third_party_change_even_if_final_is_highest():
    guard, guild, _ = make_recovery()
    now = int(time.time())
    await guard.protect(guild, now=now)
    guild.audit_entries.insert(
        0,
        SimpleNamespace(
            created_at=datetime.now(timezone.utc),
            user=SimpleNamespace(id=999),
            before=SimpleNamespace(verification_level=discord.VerificationLevel.high),
            after=SimpleNamespace(verification_level=discord.VerificationLevel.highest),
        ),
    )
    assert (await guard.restore_due(now=now + 901))["deferred"] == 1
    assert len(guild.edits) == 1


@pytest.mark.asyncio
async def test_raid_restoration_refuses_no_proof_bot_raised_level():
    guard, guild, _ = make_recovery()
    now = int(time.time())
    await guard.protect(guild, now=now)
    guild.audit_entries.clear()
    assert (await guard.restore_due(now=now + 901))["deferred"] == 1
    assert len(guild.edits) == 1


@pytest.mark.asyncio
async def test_manually_maximum_verification_is_never_overwritten_or_saved():
    guild = FakeGuild(original=discord.VerificationLevel.highest)
    guard, _, db = make_recovery(guild)
    assert await guard.protect(guild) is False
    assert guild.edits == []
    assert await db.fetchone(
        "SELECT * FROM sentrix_raid_verification_restore WHERE guild_id = ?", (guild.id,)
    ) is None


@pytest.mark.asyncio
async def test_failed_raise_removes_snapshot_instead_of_restoring_wrong_level():
    guard, guild, db = make_recovery()
    response = SimpleNamespace(status=403, reason="Forbidden")
    guild.edit_exception = discord.Forbidden(response, {"message": "Missing Permissions", "code": 50013})
    assert await guard.protect(guild) is False
    assert await db.fetchone(
        "SELECT * FROM sentrix_raid_verification_restore WHERE guild_id = ?", (guild.id,)
    ) is None
    assert guild.verification_level == discord.VerificationLevel.medium
