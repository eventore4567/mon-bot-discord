from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.automod import AutoMod
from database.db import Database


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


def _member(
    *,
    user_id: int = 7,
    role_ids: tuple[int, ...] = (),
    administrator: bool = False,
    manage_guild: bool = False,
    full_staff: bool = False,
) -> discord.Member:
    guild = Mock(spec=discord.Guild)
    guild.id = 1
    guild.owner_id = 999

    member = Mock(spec=discord.Member)
    member.id = user_id
    member.bot = False
    member.guild = guild
    member.roles = [SimpleNamespace(id=role_id) for role_id in role_ids]
    member.guild_permissions = SimpleNamespace(
        administrator=administrator,
        manage_guild=manage_guild or full_staff,
        manage_channels=full_staff,
        manage_roles=full_staff,
        manage_messages=full_staff,
        kick_members=full_staff,
        ban_members=full_staff,
    )
    return member


def _message(member: discord.Member, *, channel_id: int = 55, parent_id: int = 0):
    message = Mock(spec=discord.Message)
    message.author = member
    message.guild = member.guild
    message.channel = SimpleNamespace(id=channel_id, parent_id=parent_id)
    return message


def _policy(cog: AutoMod, name: str, *, roles=(), members=(), strict=()) -> None:
    cog.security_filter_policy_cache[(1, name)] = {
        "role_ids": set(roles),
        "member_ids": set(members),
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
@pytest.mark.parametrize("filter_name", ["antilink", "antiinvite", "blacklist_link"])
async def test_administrator_can_post_links_and_invites_even_in_strict_channels(filter_name):
    cog = _cog()
    member = _member(administrator=True)
    cog.immunity_overrides_cache[(1, member.id)] = None
    _policy(cog, "antilink", strict=(77,))
    _policy(cog, "antiinvite", strict=(77,))

    assert await cog.security_filter_applies_to(
        _message(member, channel_id=77), filter_name,
    ) is False
    assert await cog.security_filter_applies_to(
        _message(member, channel_id=501, parent_id=77), filter_name,
    ) is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filter_name",
    [
        "antispam", "antilink", "antiinvite", "antimention",
        "anticaps", "antiemoji", "antiscam", "antiinsult",
        "antispam_duplicate", "blacklist_link", "blacklist_word",
        "multilingual_toxicity",
    ],
)
@pytest.mark.parametrize("override", [None, False])
async def test_admin_bypasses_all_message_filters_even_strict_and_override_off(filter_name, override):
    cog = _cog()
    member = _member(administrator=True)
    cog.immunity_overrides_cache[(1, member.id)] = override
    _policy(cog, "antilink", strict=(77,))
    _policy(cog, "antispam", strict=(77,))
    _policy(cog, "antiinvite", strict=(77,))
    _policy(cog, "antiscam", strict=(77,))
    _policy(cog, "antiinsult", strict=(77,))
    _policy(cog, filter_name, strict=(77,))
    assert await cog.security_filter_applies_to(_message(member, channel_id=77), filter_name) is False
    assert await cog.security_filter_applies_to(
        _message(member, channel_id=555, parent_id=77), filter_name
    ) is False


@pytest.mark.asyncio
async def test_anti_nuke_server_guard_is_not_bypassed_by_message_filter_policy():
    cog = _cog()
    member = _member(administrator=True)
    assert await cog.security_filter_applies_to(_message(member), "antinuke") is True


@pytest.mark.asyncio
async def test_administrator_is_exempt_in_legacy_automod_access_check():
    cog = _cog()
    member = _member(administrator=True)
    cog.immunity_overrides_cache[(1, member.id)] = False
    assert await cog.is_automod_exempt(member) is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filter_name",
    [
        "antispam", "antilink", "antiinvite", "antimention",
        "anticaps", "antiemoji", "antiscam", "antiinsult",
    ],
)
async def test_full_permissions_staff_bypasses_every_message_filter(filter_name):
    cog = _cog()
    member = _member(full_staff=True)
    cog.immunity_overrides_cache[(1, member.id)] = False
    _policy(cog, filter_name, strict=(77,))
    assert await cog.security_filter_applies_to(
        _message(member, channel_id=77), filter_name,
    ) is False


@pytest.mark.asyncio
async def test_full_permissions_staff_skips_message_and_deletion_synchronously():
    cog = _cog()
    member = _member(full_staff=True)
    msg = _message(member)
    msg.id = 2026
    msg.content = "free nitro claim https://discord.com@fake-prize.example"
    msg.delete = AsyncMock()
    cog.automod_cache[1] = {"antispam": 1, "antiscam": 1, "antilink": 1}
    cog._delete_and_warn = AsyncMock()
    await cog.on_message(msg)
    cog._delete_and_warn.assert_not_awaited()
    await AutoMod._delete_and_warn(cog, msg, "possible scam", "antiscam")
    msg.delete.assert_not_awaited()


def test_permission_helper_does_not_exempt_partial_staff_or_role_names():
    from utils.security_member_bypass import can_bypass_message_filters

    assert can_bypass_message_filters(_member(full_staff=True)) is True
    assert can_bypass_message_filters(_member(administrator=True)) is True
    assert can_bypass_message_filters(_member(manage_guild=True)) is False
    mock_staff = _member()
    mock_staff.roles = [SimpleNamespace(id=123, name="Administrateur")]
    assert can_bypass_message_filters(mock_staff) is False


@pytest.mark.asyncio
async def test_antigif_runtime_skips_full_permission_staff_but_not_regular_users():
    from cogs.security_owner_immunity_final import _patch_antigif

    runtime = SimpleNamespace(handle_message=AsyncMock(return_value="filtered"))
    bot = SimpleNamespace(_sentrix_antigif_runtime=runtime)
    _patch_antigif(bot)

    admin = _member(full_staff=True)
    regular = _member()
    assert await runtime.handle_message(_message(admin)) is None
    assert await runtime.handle_message(_message(regular)) == "filtered"
    runtime.handle_message.__func__._sentrix_owner_antigif_immunity is True


@pytest.mark.asyncio
async def test_manage_server_without_administrator_is_not_all_perms():
    cog = _cog()
    member = _member(manage_guild=True)
    cog.immunity_overrides_cache[(1, member.id)] = None
    _policy(cog, "antilink", strict=(77,))
    _policy(cog, "antiinvite", strict=(77,))

    assert await cog.security_filter_applies_to(_message(member), "antilink") is True
    assert await cog.security_filter_applies_to(_message(member, channel_id=77), "antiinvite") is True


@pytest.mark.asyncio
async def test_member_bypass_is_per_filter_and_does_not_require_a_role():
    cog = _cog()
    member = _member(user_id=7)
    message = _message(member)
    cog.immunity_overrides_cache[(1, member.id)] = None
    _policy(cog, "antiinsult", members=(7,))
    _policy(cog, "antilink")

    assert await cog.security_filter_applies_to(message, "antiinsult") is False
    assert await cog.security_filter_applies_to(message, "antilink") is True


@pytest.mark.asyncio
async def test_strict_channel_and_its_threads_override_individual_bypass():
    cog = _cog()
    member = _member(user_id=7)
    cog.immunity_overrides_cache[(1, member.id)] = None
    _policy(cog, "antiscam", members=(7,), strict=(77,))

    assert await cog.security_filter_applies_to(_message(member, channel_id=77), "antiscam") is True
    assert await cog.security_filter_applies_to(
        _message(member, channel_id=999, parent_id=77), "antiscam"
    ) is True
    assert await cog.security_filter_applies_to(_message(member, channel_id=78), "antiscam") is False


@pytest.mark.asyncio
async def test_member_bypass_disables_unrepresentable_native_discord_rule():
    cog = _cog()
    guild = Mock(spec=discord.Guild)
    guild.id = 1
    _policy(cog, "antilink", members=(7,))

    assert await cog._native_policy_exemptions(guild, "antilink") is None


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


@pytest.mark.asyncio
async def test_database_policy_roundtrip_and_antispam_legacy_bridge(tmp_path):
    db = Database(str(tmp_path / "sentrix-security-policy.db"))
    await db.connect()
    try:
        await db.set_security_filter_policy(
            123,
            "antispam",
            role_ids=[11, 22, 11],
            member_ids=[901, 902, 901],
            strict_channel_ids=[77, 88, 77],
        )

        policy = await db.get_security_filter_policy(123, "antispam")
        assert policy == {
            "role_ids": [11, 22],
            "member_ids": [901, 902],
            "strict_channel_ids": [77, 88],
        }

        legacy_roles = await db.fetchall(
            "SELECT role_id FROM antispam_exempt_roles WHERE guild_id=? ORDER BY role_id",
            (123,),
        )
        legacy_channels = await db.fetchall(
            "SELECT channel_id FROM antispam_protected_channels "
            "WHERE guild_id=? ORDER BY channel_id",
            (123,),
        )
        legacy_policy = await db.fetchone(
            "SELECT scope_mode FROM antispam_policy WHERE guild_id=?",
            (123,),
        )

        assert [int(row["role_id"]) for row in legacy_roles] == [11, 22]
        assert [int(row["channel_id"]) for row in legacy_channels] == [77, 88]
        assert legacy_policy["scope_mode"] == "all"

        # Les anciens clients V1 qui ne transmettent aucun membre ne doivent
        # pas effacer les exemptions ajoutées par le nouveau dashboard.
        await db.set_security_filter_policy(
            123, "antispam", role_ids=[11], strict_channel_ids=[77],
        )
        assert (await db.get_security_filter_policy(123, "antispam"))["member_ids"] == [901, 902]
        # Une liste vide envoyée volontairement retire ces membres.
        await db.set_security_filter_policy(
            123, "antispam", role_ids=[11], member_ids=[], strict_channel_ids=[77],
        )
        assert (await db.get_security_filter_policy(123, "antispam"))["member_ids"] == []
    finally:
        await db.close()


def test_dashboard_has_searchable_member_bypass_and_save_transport():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    source = (root / "web/dashboard_ui/js/30_modules.js").read_text(encoding="utf-8")
    assert "securityPolicyMemberSearch" in source
    assert "data-security-add-member" in source
    assert "data-security-remove-member" in source
    assert "member_ids: memberIds" in source


@pytest.mark.asyncio
async def test_admin_is_not_blocked_by_early_message_blacklist_or_spam_or_scam():
    from unittest.mock import patch

    cog = _cog()
    member = _member(administrator=True)
    member.bot = False
    message = _message(member)
    message.content = "free nitro claim https://discord.com@fake-nitro.example"
    message.id = 123456
    message.delete = AsyncMock()
    # Même les listes noires et l'escalade ne doivent pas toucher un admin.
    cog.blacklist_users_cache[1] = {member.id}
    cog.blacklist_links_cache[1] = ["fake-nitro.example"]
    cog.blacklist_words_cache[1] = ["nitro"]
    cog.automod_cache[1] = {
        "antispam": 1, "antilink": 1, "antilink_strict": 1,
        "antiinvite": 1, "antiscam": 1, "antiinsult": 1,
    }
    cog._delete_and_warn = AsyncMock()
    with patch.object(cog, "get_immunity_override_cached", AsyncMock(side_effect=AssertionError("bypass avant DB"))):
        await cog.on_message(message)
    cog._delete_and_warn.assert_not_awaited()
    message.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_automod_deletion_guard_never_removes_admin_message():
    cog = _cog()
    member = _member(administrator=True)
    message = _message(member)
    message.id = 222
    message.delete = AsyncMock()
    await cog._delete_and_warn(message, "Lien suspect", "antiscam")
    message.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_regular_members_still_subject_to_spam_and_scam():
    cog = _cog()
    member = _member(administrator=False, manage_guild=False)
    cog.immunity_overrides_cache[(1, member.id)] = None
    _policy(cog, "antispam")
    _policy(cog, "antiscam")
    assert await cog.security_filter_applies_to(_message(member), "antispam") is True
    assert await cog.security_filter_applies_to(_message(member), "antiscam") is True
