from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.automod import AutoMod


def _cog() -> AutoMod:
    db = SimpleNamespace(
        fetchone=AsyncMock(return_value=None),
        fetchall=AsyncMock(return_value=[]),
        get_automod=AsyncMock(return_value={}),
        log_automod_action=AsyncMock(),
    )
    bot = SimpleNamespace(db=db)
    cog = AutoMod(bot)
    cog.exempt_roles_cache[1] = set()
    cog.ignored_channels_cache[1] = set()
    return cog


def _member(*, user_id: int = 7, role_ids: tuple[int, ...] = ()) -> discord.Member:
    guild = Mock(spec=discord.Guild)
    guild.id = 1
    guild.owner_id = 999

    member = Mock(spec=discord.Member)
    member.id = user_id
    member.bot = False
    member.guild = guild
    member.roles = [SimpleNamespace(id=role_id) for role_id in role_ids]
    return member


def _message(member: discord.Member, *, channel_id: int = 55, parent_id: int = 0):
    message = Mock(spec=discord.Message)
    message.author = member
    message.guild = member.guild
    message.channel = SimpleNamespace(id=channel_id, parent_id=parent_id)
    return message


def _policy(cog: AutoMod, name: str, *, roles=(), strict=()) -> None:
    cog.security_filter_policy_cache[(1, name)] = {
        "role_ids": set(roles),
        "strict_channel_ids": set(strict),
    }


@pytest.mark.asyncio
async def test_role_bypass_applies_only_to_its_filter_outside_strict_channel():
    cog = _cog()
    member = _member(role_ids=(123,))
    message = _message(member)
    cog.immunity_overrides_cache[(1, member.id)] = None
    _policy(cog, "antispam", roles=(123,))
    _policy(cog, "antilink")

    assert await cog.security_filter_applies_to(message, "antispam") is False
    assert await cog.security_filter_applies_to(message, "antilink") is True


@pytest.mark.asyncio
async def test_strict_channel_overrides_filter_role_bypass():
    cog = _cog()
    member = _member(role_ids=(123,))
    message = _message(member, channel_id=77)
    cog.immunity_overrides_cache[(1, member.id)] = None
    _policy(cog, "antispam", roles=(123,), strict=(77,))

    assert await cog.security_filter_applies_to(message, "antispam") is True


@pytest.mark.asyncio
async def test_strict_channel_overrides_legacy_global_exempt_role():
    cog = _cog()
    member = _member(role_ids=(456,))
    message = _message(member, channel_id=88)
    cog.immunity_overrides_cache[(1, member.id)] = None
    cog.exempt_roles_cache[1] = {456}
    _policy(cog, "antilink", strict=(88,))

    assert await cog.security_filter_applies_to(message, "antilink") is True


@pytest.mark.asyncio
async def test_global_exempt_role_still_bypasses_outside_strict_channel():
    cog = _cog()
    member = _member(role_ids=(456,))
    message = _message(member, channel_id=89)
    cog.immunity_overrides_cache[(1, member.id)] = None
    cog.exempt_roles_cache[1] = {456}
    _policy(cog, "antilink", strict=(88,))

    assert await cog.security_filter_applies_to(message, "antilink") is False


@pytest.mark.asyncio
async def test_thread_inherits_strict_parent_channel():
    cog = _cog()
    member = _member(role_ids=(123,))
    message = _message(member, channel_id=500, parent_id=77)
    cog.immunity_overrides_cache[(1, member.id)] = None
    _policy(cog, "antiscam", roles=(123,), strict=(77,))

    assert await cog.security_filter_applies_to(message, "antiscam") is True


@pytest.mark.asyncio
async def test_strict_channel_has_priority_over_ignored_channel():
    cog = _cog()
    member = _member()
    message = _message(member, channel_id=42)
    cog.immunity_overrides_cache[(1, member.id)] = None
    cog.ignored_channels_cache[1] = {42}
    _policy(cog, "antimention", strict=(42,))

    assert await cog.security_filter_applies_to(message, "antimention") is True


@pytest.mark.asyncio
async def test_ignored_channel_still_skips_filter_when_not_strict():
    cog = _cog()
    member = _member()
    message = _message(member, channel_id=42)
    cog.immunity_overrides_cache[(1, member.id)] = None
    cog.ignored_channels_cache[1] = {42}
    _policy(cog, "antimention")

    assert await cog.security_filter_applies_to(message, "antimention") is False


@pytest.mark.asyncio
async def test_duplicate_spam_alias_uses_antispam_policy():
    cog = _cog()
    member = _member(role_ids=(123,))
    message = _message(member)
    cog.immunity_overrides_cache[(1, member.id)] = None
    _policy(cog, "antispam", roles=(123,))

    assert await cog.security_filter_applies_to(message, "antispam_duplicate") is False
