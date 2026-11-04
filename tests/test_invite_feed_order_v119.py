"""Invite tracker must publish only after the authoritative detector has persisted data."""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci-placeholder-not-a-real-token")
import discord  # noqa: E402
from cogs.invites import Invites  # noqa: E402
from cogs import invite_tracker_runtime as tracker  # noqa: E402


def _member():
    member = Mock(spec=discord.Member)
    member.id = 92
    member.bot = False
    member.mention = "<@92>"
    member.name = "TestMember"
    member.display_name = "TestMember"
    member.created_at = discord.utils.utcnow()
    member.guild = SimpleNamespace(id=7)
    return member


def test_join_publishes_inviter_after_database_write():
    calls = []
    bot = Mock()
    async def record(*args):
        calls.append(("record", args))
    bot.db.record_invite_join = AsyncMock(side_effect=record)
    bot.dispatch.side_effect = lambda *args: calls.append(("dispatch", args))
    cog = Invites(bot)
    cog.find_used_invite = AsyncMock(
        return_value=SimpleNamespace(code="abc", inviter=SimpleNamespace(id=42))
    )
    cog._journaliser_arrivee = AsyncMock()
    member = _member()

    asyncio.run(cog.on_member_join(member))

    assert [name for name, _args in calls] == ["record", "dispatch"]
    assert calls[1][1] == ("sentrix_invite_recorded", member, 42, "abc")
    cog._journaliser_arrivee.assert_awaited_once_with(member, "abc", 42)


def test_public_feed_uses_confirmed_attribution_not_racy_db_read():
    bot = Mock()
    bot.db.get_invite_stats = AsyncMock(return_value={"active": 3})
    cog = tracker.InviteTrackerRuntime(bot)
    member = _member()
    with patch.object(tracker, "_send_feed_message", new_callable=AsyncMock) as send:
        asyncio.run(cog.on_sentrix_invite_recorded(member, 42, "abc"))
    sent = send.await_args.args[2]
    assert "<@42>" in sent and "**3** active invites" in sent
    assert "unknown" not in sent.lower()


def test_public_feed_avoids_repetitive_unknown_inviter_messages():
    bot = Mock()
    cog = tracker.InviteTrackerRuntime(bot)
    member = _member()
    with patch.object(tracker, "_send_feed_message", new_callable=AsyncMock) as send:
        asyncio.run(cog.on_sentrix_invite_recorded(member, None, None))
    assert send.await_args.args[2] == "<@92> joined the server."
    bot.db.get_invite_stats.assert_not_called()


def test_leave_without_inviter_is_short_and_neutral():
    bot = Mock()
    bot.db.get_invited_by = AsyncMock(return_value=None)
    cog = tracker.InviteTrackerRuntime(bot)
    with patch.object(tracker, "_send_feed_message", new_callable=AsyncMock) as send, \
         patch.object(tracker.asyncio, "sleep", new_callable=AsyncMock):
        asyncio.run(cog.on_member_remove(_member()))
    assert send.await_args.args[2] == "**TestMember** left the server."


def test_no_independent_join_listener_can_race_attribution():
    from pathlib import Path
    text = Path("cogs/invite_tracker_runtime.py").read_text(encoding="utf-8")
    assert "async def on_member_join(" not in text
    assert "async def on_sentrix_invite_recorded(" in text
