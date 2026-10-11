"""Nouveaux tests anti-spam multi-salons, indépendants des anciennes simulations V1."""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from cogs import automod as automod_module  # noqa: E402
from cogs.automod import AutoMod  # noqa: E402
from services import moderation as moderation_service  # noqa: E402
from utils import sentrix_panels as panels  # noqa: E402


_ALL_OFF = {
    key: 0 for key in (
        "antispam", "antilink", "antilink_strict", "antiinvite", "antimention", "anticaps", "antiemoji",
        "antiscam", "antiraid", "antibot", "antiaccount", "antinuke", "escalation",
    )
}


def _cog(*, conf: dict) -> AutoMod:
    bot = SimpleNamespace(
        db=SimpleNamespace(
            log_automod_action=AsyncMock(),
            fetchone=AsyncMock(return_value=None),
        )
    )
    cog = AutoMod(bot)
    cog.automod_cache[1] = {**_ALL_OFF, **conf}
    cog.ignored_channels_cache[1] = set()
    cog.blacklist_words_cache[1] = []
    cog.blacklist_links_cache[1] = []
    cog.blacklist_users_cache[1] = set()
    cog.exempt_roles_cache[1] = set()
    cog.whitelist_domains_cache[1] = []
    cog.log_action = AsyncMock()
    cog.moderation_dataset = SimpleNamespace(match=lambda content: None)
    return cog


def _member() -> Mock:
    guild = Mock(spec=discord.Guild)
    guild.id = 1
    guild.owner_id = 999
    me = Mock()
    me.guild_permissions = Mock(moderate_members=True)
    me.top_role = 10
    guild.me = me
    member = Mock(spec=discord.Member)
    member.id = 7
    member.bot = False
    member.mention = "<@7>"
    member.guild = guild
    member.top_role = 1
    member.timed_out_until = None
    member.timeout = AsyncMock()
    member.roles = []
    member.guild_permissions = Mock(administrator=False, manage_guild=False)
    return member


def _message(member: Mock, index: int, content: str = "spam") -> Mock:
    message = Mock(spec=discord.Message)
    message.id = 1000 + index
    message.author = member
    message.guild = member.guild
    message.channel = Mock(id=55, mention="<#55>")
    message.content = f"{content} {index}"
    message.mentions = []
    message.role_mentions = []
    message.mention_everyone = False
    message.attachments = []
    message.delete = AsyncMock()
    return message


@pytest.mark.asyncio
async def test_anti_spam_detects_slow_cross_channel_flood_without_quick_burst():
    cog = _cog(conf={"antispam": 1})
    member = _member()
    cog._delete_and_warn = AsyncMock()
    clock = [1000.0]

    # 20 messages sur 57 secondes, quatre salons : le compteur 6s ne voit
    # jamais cinq messages, la nouvelle détection doit attraper ce schéma.
    with patch("utils.sliding_window.time.time", side_effect=lambda: clock[0]):
        for i in range(automod_module.SPAM_CROSS_CHANNEL_THRESHOLD):
            clock[0] = 1000.0 + i * 3.0
            message = _message(member, i, "contenu publicitaire distinct par message")
            message.channel.id = 55 + (i % 4)
            await cog.on_message(message)

    cog._delete_and_warn.assert_awaited_once()
    assert "plusieurs salons" in cog._delete_and_warn.await_args.args[1]
    assert cog._delete_and_warn.await_args.args[2] == "antispam"
    assert cog.cross_channel_spam_tracker.compter((1, 7), maintenant=clock[0]) == 0


@pytest.mark.asyncio
async def test_active_conversation_single_channel_is_not_cross_channel_spam():
    cog = _cog(conf={"antispam": 1})
    member = _member()
    cog._delete_and_warn = AsyncMock()
    clock = [1000.0]
    with patch("utils.sliding_window.time.time", side_effect=lambda: clock[0]):
        for i in range(automod_module.SPAM_CROSS_CHANNEL_THRESHOLD + 2):
            clock[0] = 1000.0 + i * 3.0
            message = _message(member, i, "conversation normale avec phrases distinctes")
            await cog.on_message(message)

    cog._delete_and_warn.assert_not_awaited()


@pytest.mark.asyncio
async def test_brief_replies_are_not_counted_as_cross_channel_spam():
    cog = _cog(conf={"antispam": 1})
    member = _member()
    cog._delete_and_warn = AsyncMock()
    clock = [1000.0]
    with patch("utils.sliding_window.time.time", side_effect=lambda: clock[0]):
        for i in range(automod_module.SPAM_CROSS_CHANNEL_THRESHOLD):
            clock[0] = 1000.0 + i * 3.0
            message = _message(member, i, "ok")
            message.content = "ok"
            message.channel.id = 55 + (i % 4)
            await cog.on_message(message)

    cog._delete_and_warn.assert_not_awaited()


