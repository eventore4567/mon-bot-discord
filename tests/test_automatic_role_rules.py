"""Règles de rôles automatiques : consentement admin, sécurité, réversibilité."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cogs import automatic_role_rules as rules
from cogs import setup_control_center as setup_ui


class MemoryDB:
    def __init__(self):
        self.config = {}
        self.assigned = {}

    async def execute(self, statement, values=()):
        query = " ".join(statement.split()).lower()
        if query.startswith("create table"):
            return
        if query.startswith("insert into automatic_role_rules"):
            guild_id, action, role_id = values
            self.config[(guild_id, action)] = role_id
        elif query.startswith("delete from automatic_role_rules"):
            self.config.pop((values[0], values[1]), None)
        elif query.startswith("insert into automatic_role_assignments"):
            guild_id, user_id, action, role_id = values
            self.assigned[(guild_id, user_id, action)] = role_id
        elif query.startswith("delete from automatic_role_assignments"):
            self.assigned.pop((values[0], values[1], values[2]), None)
        else:
            raise AssertionError(query)

    async def fetchone(self, statement, values=()):
        query = " ".join(statement.split()).lower()
        if "from automatic_role_rules" in query:
            role = self.config.get((values[0], values[1]))
        elif "from automatic_role_assignments" in query:
            role = self.assigned.get((values[0], values[1], values[2]))
        else:
            raise AssertionError(query)
        return {"role_id": role} if role is not None else None


class Role:
    def __init__(self, role_id, position=10, managed=False):
        self.id = role_id
        self.position = position
        self.mention = f"<@&{role_id}>"
        self.managed = managed

    def __lt__(self, other):
        return self.position < other.position

    def __ge__(self, other):
        return self.position >= other.position

    def is_default(self):
        return False


def fixture():
    db = MemoryDB()
    bot = SimpleNamespace(db=db)
    role = Role(200)
    perms = SimpleNamespace(manage_roles=True, administrator=False)
    me = SimpleNamespace(guild_permissions=perms, top_role=Role(900, 99))
    guild = SimpleNamespace(
        id=123, default_role=Role(123, 0), me=me,
        get_role=lambda rid: role if rid == 200 else None,
    )
    member = SimpleNamespace(id=321, guild=guild, roles=[])

    async def add_roles(role_to_add, **kwargs):
        member.roles.append(role_to_add)

    async def remove_roles(role_to_remove, **kwargs):
        member.roles.remove(role_to_remove)

    member.add_roles = AsyncMock(side_effect=add_roles)
    member.remove_roles = AsyncMock(side_effect=remove_roles)
    return bot, guild, member, role


@pytest.mark.asyncio
async def test_giveaway_role_is_opt_in_never_given_by_default():
    bot, _guild, member, _role = fixture()
    assert await rules.sync_giveaway_blacklist(bot, member, excluded=True) is None
    member.add_roles.assert_not_awaited()


@pytest.mark.asyncio
async def test_configured_role_is_added_then_reverted_once():
    bot, guild, member, role = fixture()
    await rules.set_giveaway_role(bot, guild.id, role.id)
    assert await rules.giveaway_role_id(bot, guild.id) == role.id
    result = await rules.sync_giveaway_blacklist(bot, member, excluded=True)
    assert role.mention in result
    member.add_roles.assert_awaited_once()
    assert bot.db.assigned[(guild.id, member.id, rules.GIVEAWAY_ACTION)] == role.id
    result = await rules.sync_giveaway_blacklist(bot, member, excluded=False)
    assert "retiré" in result
    member.remove_roles.assert_awaited_once()
    assert not bot.db.assigned


@pytest.mark.asyncio
async def test_never_remove_a_preexisting_member_role():
    bot, guild, member, role = fixture()
    member.roles.append(role)
    await rules.set_giveaway_role(bot, guild.id, role.id)
    result = await rules.sync_giveaway_blacklist(bot, member, excluded=True)
    assert "possédait déjà" in result
    assert not bot.db.assigned
    assert await rules.sync_giveaway_blacklist(bot, member, excluded=False) is None
    member.remove_roles.assert_not_awaited()
    assert role in member.roles


@pytest.mark.asyncio
async def test_permissions_denied_fail_closed_and_preserve_blacklist_decision():
    bot, guild, member, role = fixture()
    guild.me.guild_permissions.manage_roles = False
    await rules.set_giveaway_role(bot, guild.id, role.id)
    result = await rules.sync_giveaway_blacklist(bot, member, excluded=True)
    assert "permissions insuffisantes" in result
    member.add_roles.assert_not_awaited()
    assert not bot.db.assigned


@pytest.mark.asyncio
async def test_rule_can_be_disabled_without_removing_existing_member_roles():
    bot, guild, member, role = fixture()
    await rules.set_giveaway_role(bot, guild.id, role.id)
    await rules.sync_giveaway_blacklist(bot, member, excluded=True)
    await rules.set_giveaway_role(bot, guild.id, None)
    assert await rules.giveaway_role_id(bot, guild.id) is None
    # Still cleans up only the role granted earlier when unblacklisting.
    result = await rules.sync_giveaway_blacklist(bot, member, excluded=False)
    assert "retiré" in result
    member.remove_roles.assert_awaited_once()


def test_setup_shows_safe_role_selections_and_readable_safety_labels():
    assert setup_ui.CATEGORIES["auto_roles"][0] == "Rôles automatiques"
    assert "giveaway_block_role" in setup_ui._MANAGED_ROLE_FIELDS
    assert "Détection de suppressions massives de membres" in dict(setup_ui.AUTOMOD).values()
    bot, guild, member, role = fixture()
    assert setup_ui.validate_role_choice(guild, role, "giveaway_block_role") is None
    assert "au-dessus" in setup_ui.validate_role_choice(guild, Role(201, 150), "giveaway_block_role")
