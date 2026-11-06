"""Vraies lectures de base après redémarrage et sécurité des rôles automatiques."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
import pytest
import pytest_asyncio

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
from cogs.economy import _self_assignable_role_error
from cogs.verification import Verification
from database.db import Database
from utils.reaction_role_options import options, save_options


class Role(SimpleNamespace):
    def __ge__(self, other):
        return self.position >= other.position

    def is_default(self):
        return self.id == 0


def role(ident, position=1, **perms):
    p = discord.Permissions.none()
    for key, value in perms.items():
        setattr(p, key, value)
    return Role(
        id=ident,
        position=position,
        permissions=p,
        managed=False,
        name="Rôle " + str(ident),
        mention="<@&" + str(ident) + ">",
    )


@pytest_asyncio.fixture
async def state(tmp_path):
    db = Database(str(tmp_path / "reactions.db"))
    await db.connect()
    roles = {ident: role(ident) for ident in (10, 11, 12)}
    member = SimpleNamespace(id=42, bot=False, roles=[])

    async def add(*items, **kwargs):
        member.roles.extend(r for r in items if r not in member.roles)

    async def remove(*items, **kwargs):
        member.roles[:] = [r for r in member.roles if r not in items]

    member.add_roles = AsyncMock(side_effect=add)
    member.remove_roles = AsyncMock(side_effect=remove)
    message = SimpleNamespace(remove_reaction=AsyncMock())
    channel = SimpleNamespace(fetch_message=AsyncMock(return_value=message))
    guild = SimpleNamespace(
        id=1,
        owner_id=2,
        owner=SimpleNamespace(send=AsyncMock()),
        me=SimpleNamespace(
            guild_permissions=SimpleNamespace(manage_roles=True), top_role=role(99, 99)
        ),
        get_role=roles.get,
        get_member=lambda ident: member,
        get_channel=lambda ident: channel,
    )
    bot = SimpleNamespace(
        db=db, get_guild=lambda ident: guild, user=SimpleNamespace(id=99)
    )
    for rid, emoji in ((10, "🎁"), (11, "🎪")):
        await db.execute(
            "INSERT INTO reaction_roles (guild_id,channel_id,message_id,emoji,emoji_key,role_id,label,created_by) VALUES (1,2,3,?,?,?,?,42)",
            (emoji, "unicode:" + emoji, rid, "Rôle"),
        )
    yield SimpleNamespace(
        bot=bot, guild=guild, member=member, roles=roles, message=message
    )
    await db.close()


def event(state, emoji="🎁"):
    return SimpleNamespace(
        guild_id=1,
        channel_id=2,
        message_id=3,
        user_id=42,
        member=state.member,
        emoji=discord.PartialEmoji(name=emoji),
    )


@pytest.mark.asyncio
async def test_add_and_remove_read_database_after_restart(state):
    cog = Verification(state.bot)
    await cog.on_raw_reaction_add(event(state))
    assert state.roles[10] in state.member.roles
    restarted = Verification(
        SimpleNamespace(
            db=state.bot.db, get_guild=state.bot.get_guild, user=state.bot.user
        )
    )
    await restarted.on_raw_reaction_remove(event(state))
    assert state.roles[10] not in state.member.roles


@pytest.mark.asyncio
async def test_single_role_removes_first_role_and_its_reaction(state):
    await save_options(state.bot, 1, 3, {"single_role": 1})
    cog = Verification(state.bot)
    await cog.on_raw_reaction_add(event(state))
    await cog.on_raw_reaction_add(event(state, "🎪"))
    assert (
        state.roles[11] in state.member.roles
        and state.roles[10] not in state.member.roles
    )
    state.message.remove_reaction.assert_any_await("🎁", state.member)


@pytest.mark.asyncio
async def test_required_role_blocks_and_removes_reaction(state):
    await save_options(state.bot, 1, 3, {"required_role_id": 12})
    await Verification(state.bot).on_raw_reaction_add(event(state))
    state.member.add_roles.assert_not_awaited()
    state.message.remove_reaction.assert_awaited_once()
    state.member.roles = [state.roles[12]]
    await Verification(state.bot).on_raw_reaction_add(event(state))
    assert state.roles[10] in state.member.roles


@pytest.mark.asyncio
async def test_remove_option_is_persistent_and_deleted_roles_are_ignored(state):
    await save_options(state.bot, 1, 3, {"remove_on_unreact": 0})
    cog = Verification(state.bot)
    await cog.on_raw_reaction_add(event(state))
    await Verification(state.bot).on_raw_reaction_remove(event(state))
    assert state.roles[10] in state.member.roles
    del state.roles[10]
    await cog.on_raw_reaction_add(event(state))
    assert (await options(state.bot, 1, 3))["remove_on_unreact"] == 0


@pytest.mark.parametrize(
    "permission",
    [
        "administrator",
        "manage_guild",
        "manage_roles",
        "manage_channels",
        "ban_members",
        "kick_members",
        "manage_webhooks",
        "mention_everyone",
        "moderate_members",
    ],
)
def test_every_dangerous_permission_is_rejected(permission):
    guild = SimpleNamespace(me=SimpleNamespace(top_role=role(99, 99)))
    assert _self_assignable_role_error(guild, role(10, **{permission: True}))


@pytest.mark.parametrize("kind", ["everyone", "managed", "too_high"])
def test_everyone_managed_and_high_roles_are_rejected(kind):
    guild = SimpleNamespace(me=SimpleNamespace(top_role=role(99, 99)))
    chosen = role(0 if kind == "everyone" else 10, 100 if kind == "too_high" else 1)
    chosen.managed = kind == "managed"
    assert _self_assignable_role_error(guild, chosen)


@pytest.mark.asyncio
async def test_forbidden_only_notifies_owner_once_per_six_hours_across_restart(state):
    state.member.add_roles = AsyncMock(
        side_effect=discord.Forbidden(
            SimpleNamespace(status=403, reason="Forbidden"), "missing hierarchy"
        )
    )
    with patch("utils.reaction_role_options.time.time", return_value=100000):
        await Verification(state.bot).on_raw_reaction_add(event(state))
        await Verification(state.bot).on_raw_reaction_add(event(state))
    state.guild.owner.send.assert_awaited_once()
    with patch("utils.reaction_role_options.time.time", return_value=121601):
        await Verification(state.bot).on_raw_reaction_add(event(state))
    assert state.guild.owner.send.await_count == 2


@pytest.mark.asyncio
async def test_bots_and_missing_roles_do_not_assign(state):
    state.member.bot = True
    await Verification(state.bot).on_raw_reaction_add(event(state))
    state.member.add_roles.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_reaction_panels_are_manageable_without_double_listeners(state):
    import sentrix_regression_runtime as runtime
    from utils.reaction_role_options import import_legacy_panels

    await state.bot.db.execute(runtime._ROLE_PANEL_SCHEMA)
    await state.bot.db.execute(runtime._REACTION_SCHEMA)
    await state.bot.db.execute(
        'INSERT INTO sentrix_role_panels (message_id,guild_id,channel_id,mode,role_ids_json,mappings_json,created_by,created_at) VALUES (4,1,2,\'reaction\',\'[10]\',\'[{"emoji":"🎁","key":"unicode:🎁","role_id":10}]\',42,1)'
    )
    await import_legacy_panels(state.bot, 1)
    assert await state.bot.db.fetchone(
        "SELECT * FROM reaction_role_panels WHERE guild_id=1 AND message_id=4"
    )
    cog = runtime.SentriXRegressionRuntime(state.bot)
    ev = event(state)
    ev.message_id = 4
    await cog._apply_reaction(ev, add=True)
    state.member.add_roles.assert_not_awaited()  # le listener canonique prend la main
    await Verification(state.bot).on_raw_reaction_add(ev)
    assert state.roles[10] in state.member.roles


@pytest.mark.asyncio
async def test_voluntary_owner_exception_is_limited_to_exact_safe_roles(state):
    from utils.reaction_role_options import (
        _SELF_SERVICE_REMOVAL,
        voluntary_removal_allowed,
    )

    state.member.guild = state.guild
    privileged = role(13, administrator=True)
    allowed = state.roles[10]
    token = _SELF_SERVICE_REMOVAL.set(
        (state.guild.id, state.member.id, {allowed.id, privileged.id})
    )
    try:
        assert voluntary_removal_allowed(state.member, [allowed])
        assert not voluntary_removal_allowed(state.member, [privileged])
        assert not voluntary_removal_allowed(state.member, [state.roles[11]])
        other = SimpleNamespace(id=43, guild=state.guild)
        assert not voluntary_removal_allowed(other, [allowed])
        assert not voluntary_removal_allowed(state.member, [])
    finally:
        _SELF_SERVICE_REMOVAL.reset(token)
    assert not voluntary_removal_allowed(state.member, [allowed])


@pytest.mark.asyncio
async def test_failed_role_removal_does_not_leave_owner_exception_enabled(state):
    from utils.reaction_role_options import _SELF_SERVICE_REMOVAL, apply_reaction

    state.member.remove_roles.side_effect = discord.HTTPException(
        SimpleNamespace(status=500, reason="error"), "Échec simulé"
    )
    await apply_reaction(state.bot, event(state), {"role_id": 10}, adding=False)
    assert _SELF_SERVICE_REMOVAL.get() is None
