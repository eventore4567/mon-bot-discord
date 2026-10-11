"""Garanties d'idempotence des sanctions quand plusieurs cogs détectent le même message."""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.automod import AutoMod
from utils.automod_message_claims import AutomodMessageClaims


def _runtime(*, administrator=False, manage_guild=False):
    guild = Mock(spec=discord.Guild)
    guild.id = 27
    guild.owner_id = 999
    guild.me = SimpleNamespace(
        top_role=100, guild_permissions=SimpleNamespace(moderate_members=True)
    )
    member = Mock(spec=discord.Member)
    member.id = 45
    member.bot = False
    member.mention = "<@45>"
    member.guild_permissions = SimpleNamespace(
        administrator=administrator, manage_guild=manage_guild
    )
    member.top_role = 10
    member.guild = guild
    channel = SimpleNamespace(id=54, mention="<#54>", send=AsyncMock())
    message = SimpleNamespace(
        id=123456,
        guild=guild,
        author=member,
        channel=channel,
        content="https://example.net/hello",
        delete=AsyncMock(),
        attachments=[],
    )
    bot = SimpleNamespace(
        db=SimpleNamespace(log_automod_action=AsyncMock())
    )
    cog = AutoMod(bot)
    cog._record_incident_trace = AsyncMock()
    cog._flush_incident_log = AsyncMock()
    cog._maybe_escalate = AsyncMock(return_value=(None, 0))
    cog.add_risk_signal = AsyncMock(return_value=0)
    return cog, message


def test_claims_deduplicate_across_filters_and_expire():
    guard = AutomodMessageClaims(ttl_seconds=30, max_entries=3)
    assert guard.claim(1, 22, now=100)
    assert not guard.claim(1, 22, now=101)
    assert guard.claim(2, 22, now=101)
    assert guard.claim(1, 23, now=101)
    assert guard.claim(1, 24, now=101)
    assert len(guard) == 3
    assert guard.claim(1, 22, now=151)
    assert len(guard) <= 3
    assert not guard.claim(1, 22, now=152)


@pytest.mark.asyncio
async def test_two_concurrent_listeners_cannot_delete_or_warn_twice():
    cog, message = _runtime()
    started = asyncio.Event()
    resume = asyncio.Event()

    async def slow_delete():
        started.set()
        await resume.wait()

    message.delete.side_effect = slow_delete
    first = asyncio.create_task(
        cog._delete_and_warn(message, "Lien interdit", "antilink", allow_escalation=False)
    )
    await asyncio.wait_for(started.wait(), timeout=1.0)

    await cog._delete_and_warn(
        message, "Image dangereuse", "dangerous_attachment", allow_escalation=False,
    )
    resume.set()
    await first
    await asyncio.sleep(0)

    message.delete.assert_awaited_once()
    cog.bot.db.log_automod_action.assert_awaited_once()
    message.channel.send.assert_awaited_once()
    cog._record_incident_trace.assert_awaited_once()
    assert len(cog._sanctioned_messages) == 1


@pytest.mark.asyncio
async def test_timeout_and_regular_filter_share_same_claim():
    cog, message = _runtime()
    started = asyncio.Event()
    resume = asyncio.Event()

    async def slow_delete():
        started.set()
        await resume.wait()

    message.delete.side_effect = slow_delete
    first = asyncio.create_task(
        cog._delete_and_warn(message, "spam", "antispam", allow_escalation=False)
    )
    await asyncio.wait_for(started.wait(), timeout=1.0)

    # L'autre listener veut appliquer un timeout au même message.
    await cog._delete_and_timeout(message, "Insulte", detection_kind="offensive")
    resume.set()
    await first
    await asyncio.sleep(0)

    message.delete.assert_awaited_once()
    cog.bot.db.log_automod_action.assert_awaited_once()


@pytest.mark.asyncio
async def test_timeout_direct_path_never_punishes_manage_server_admin():
    cog, message = _runtime(manage_guild=True)
    await cog._delete_and_timeout(message, "Texte suspect", detection_kind="offensive")
    message.delete.assert_not_awaited()
    cog.bot.db.log_automod_action.assert_not_awaited()
    assert len(cog._sanctioned_messages) == 0


@pytest.mark.asyncio
async def test_distinct_messages_still_get_deleted_during_single_incident():
    cog, message = _runtime()
    await cog._delete_and_warn(message, "Lien interdit", "antilink", allow_escalation=False)
    second = SimpleNamespace(**vars(message))
    second.id = message.id + 1
    second.delete = AsyncMock()
    await cog._delete_and_warn(second, "Lien interdit", "antilink", allow_escalation=False)
    await asyncio.sleep(0)

    message.delete.assert_awaited_once()
    second.delete.assert_awaited_once()
    # Les messages distincts comptent pour un seul incident : pas deux avertissements.
    cog.bot.db.log_automod_action.assert_awaited_once()
    message.channel.send.assert_awaited_once()
    assert len(cog._sanctioned_messages) == 2
