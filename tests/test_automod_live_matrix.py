from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import automod as automod_module
from cogs.automod import AutoMod


def _base_conf(**updates):
    conf = {
        key: 0
        for key in (
            "antispam",
            "antilink",
            "antilink_strict",
            "antiinvite",
            "antimention",
            "anticaps",
            "antiemoji",
            "antiscam",
            "antiraid",
            "antibot",
            "antiaccount",
            "antinuke",
            "antiinsult",
            "escalation",
        )
    }
    conf.update(updates)
    return conf


def _cog(conf):
    bot = SimpleNamespace(
        db=SimpleNamespace(
            fetchone=AsyncMock(return_value=None),
            fetchall=AsyncMock(return_value=[]),
            get_automod=AsyncMock(return_value=conf),
        )
    )
    cog = AutoMod(bot)
    cog.automod_cache[1] = conf
    cog.ignored_channels_cache[1] = set()
    cog.blacklist_words_cache[1] = []
    cog.blacklist_links_cache[1] = []
    cog.blacklist_users_cache[1] = set()
    cog.exempt_roles_cache[1] = set()
    cog.whitelist_domains_cache[1] = []
    cog.moderation_dataset = SimpleNamespace(match=lambda _content: None)
    cog._delete_and_warn = AsyncMock()
    cog._delete_and_timeout = AsyncMock()
    return cog


def _member(*, user_id=7, owner_id=999, manage_guild=False):
    guild = Mock(spec=discord.Guild)
    guild.id = 1
    guild.owner_id = owner_id
    me = Mock()
    me.top_role = 100
    me.guild_permissions = Mock(manage_guild=True, moderate_members=True)
    guild.me = me

    member = Mock(spec=discord.Member)
    member.id = user_id
    member.bot = False
    member.guild = guild
    member.roles = []
    member.top_role = 10
    member.guild_permissions = Mock(
        administrator=False,
        manage_guild=manage_guild,
    )
    return member


def _message(member, content):
    message = Mock(spec=discord.Message)
    message.id = 12345
    message.author = member
    message.guild = member.guild
    message.channel = Mock(id=55)
    message.content = content
    message.mentions = []
    message.role_mentions = []
    message.mention_everyone = False
    message.attachments = []
    message.delete = AsyncMock()
    return message


@pytest.mark.asyncio
async def test_normal_member_is_blocked_by_strict_antilink():
    cog = _cog(_base_conf(antilink=1, antilink_strict=1))
    message = _message(_member(), "https://example.com")

    await cog.on_message(message)

    cog._delete_and_warn.assert_awaited_once()
    assert cog._delete_and_warn.await_args.args[2] == "antilink"


@pytest.mark.asyncio
async def test_admin_is_still_filtered_when_not_explicitly_exempt():
    cog = _cog(_base_conf(antilink=1, antilink_strict=1))
    message = _message(_member(manage_guild=True), "https://example.com")

    await cog.on_message(message)

    cog._delete_and_warn.assert_awaited_once()


@pytest.mark.asyncio
async def test_server_owner_default_immunity_skips_strict_filter():
    cog = _cog(_base_conf(antilink=1, antilink_strict=1))
    owner = _member(user_id=999, owner_id=999)
    message = _message(owner, "https://example.com")

    with patch.object(automod_module.config, "OWNER_IDS", set()):
        await cog.on_message(message)

    cog._delete_and_warn.assert_not_awaited()


@pytest.mark.asyncio
async def test_server_owner_immunity_off_is_filtered_like_normal_member():
    cog = _cog(_base_conf(antilink=1, antilink_strict=1))
    owner = _member(user_id=999, owner_id=999)
    cog.immunity_overrides_cache[(1, 999)] = False
    message = _message(owner, "https://example.com")

    await cog.on_message(message)

    cog._delete_and_warn.assert_awaited_once()


@pytest.mark.asyncio
async def test_targeted_word_and_link_are_combined_in_one_action():
    cog = _cog(_base_conf())
    cog.blacklist_words_cache[1] = ["interdit"]
    cog.blacklist_links_cache[1] = ["example.com"]
    message = _message(_member(), "interdit https://example.com")

    await cog.on_message(message)

    cog._delete_and_warn.assert_awaited_once()
    args = cog._delete_and_warn.await_args
    assert args.args[2] == "blacklist_word_link"
    assert args.kwargs["censored_content"] is not None
    assert "example.com" not in args.kwargs["censored_content"]


def test_obfuscated_and_concatenated_links_are_normalized():
    raw = (
        "https:/ /discord.gg/Test"
        "https://example.com"
        " hxxps://evil[.]example"
    )
    normalized = automod_module._normalize_link_text(raw)

    assert "https://discord.gg/test" in normalized
    assert " https://example.com" in normalized
    assert "hxxps://evil.example" in normalized


@pytest.mark.asyncio
async def test_native_rule_is_recreated_after_manual_deletion():
    conf = _base_conf(antilink=1, antilink_strict=1)
    bot = SimpleNamespace(
        db=SimpleNamespace(get_automod=AsyncMock(return_value=conf))
    )
    cog = AutoMod(bot)
    guild = SimpleNamespace(
        id=1,
        me=SimpleNamespace(
            guild_permissions=SimpleNamespace(manage_guild=True)
        ),
        fetch_automod_rules=AsyncMock(return_value=[]),
        create_automod_rule=AsyncMock(),
    )

    ok = await cog._sync_native_antilink_rule(guild)

    assert ok is True
    guild.create_automod_rule.assert_awaited_once()


@pytest.mark.asyncio
async def test_native_permission_failure_keeps_local_filter_available():
    conf = _base_conf(antilink=1, antilink_strict=1)
    bot = SimpleNamespace(
        db=SimpleNamespace(get_automod=AsyncMock(return_value=conf))
    )
    cog = AutoMod(bot)
    guild = SimpleNamespace(
        id=1,
        me=SimpleNamespace(
            guild_permissions=SimpleNamespace(manage_guild=False)
        ),
    )

    native_ok = await cog._sync_native_antilink_rule(guild)
    assert native_ok is False

    # The local listener is independent from native Discord AutoMod.
    cog.automod_cache[1] = conf
    cog.ignored_channels_cache[1] = set()
    cog.blacklist_words_cache[1] = []
    cog.blacklist_links_cache[1] = []
    cog.blacklist_users_cache[1] = set()
    cog.exempt_roles_cache[1] = set()
    cog.whitelist_domains_cache[1] = []
    cog.immunity_overrides_cache[(1, 7)] = False
    cog._delete_and_warn = AsyncMock()
    member = _member()
    member.guild = guild
    guild.owner_id = 999
    message = _message(member, "https://example.com")
    message.guild = guild

    await cog.on_message(message)

    cog._delete_and_warn.assert_awaited_once()
