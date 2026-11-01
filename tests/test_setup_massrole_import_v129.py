"""Régression : +setup public en lecture seule, /role mass, migration d'un bot."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
import pytest
from discord import app_commands

from cogs import bot_data_import, server_choice_roles, setup_invitations
from utils import access_matrix, slash_catalog, stats_service


def _walk(items):
    for item in items:
        yield item
        yield from _walk(getattr(item, "children", ()))


def test_any_member_can_open_setup_without_receiving_mutation_controls():
    # La racine reste classée configuration afin d'éviter une double ACL ;
    # son entrée seulement est publique via la politique readonly.
    assert "setup" in access_matrix.CATEGORY_COMMANDS["configuration"]
    assert "setup" not in access_matrix.PUBLIC_COMMANDS
    view = setup_invitations._readonly_setup_view(SimpleNamespace(name="Serveur test"))
    assert isinstance(view, discord.ui.LayoutView)
    text = "\n".join(
        item.content for item in _walk(view.children) if isinstance(item, discord.ui.TextDisplay)
    )
    assert "Centre du serveur" in text
    assert "Gérer le serveur" in text
    assert not any(isinstance(item, (discord.ui.Button, discord.ui.Select))
                   for item in _walk(view.children))
    code = (Path(__file__).parents[1] / "cogs/setup_invitations.py").read_text()
    assert "return await panels.envoyer(target, view, ephemere=False)" in code
    assert "_readonly_setup_view(guild)" in code
    assert "return await panels.envoyer(target, view, ephemere=True)" in code


class _Role:
    def __init__(self, name="@Role", position=1):
        self.name = name
        self.mention = name
        self.position = position
        self.managed = False

    def is_default(self):
        return False

    def __ge__(self, other):
        return self.position >= other.position


class _Member:
    def __init__(self, member_id, *, bot=False):
        self.id, self.bot = member_id, bot
        self.roles = []
        self.add_roles = AsyncMock()
        self.remove_roles = AsyncMock()


async def _all_members(members):
    for member in members:
        yield member


@pytest.mark.asyncio
@pytest.mark.parametrize("target,expected", [
    ("members", {1, 2}), ("bots", {3, 4}), ("both", {1, 2, 3, 4}),
    ("membres", {1, 2}), ("tous", {1, 2, 3, 4}),
])
async def test_massrole_real_execution_targets_humans_bots_or_both(target, expected):
    members = [_Member(1), _Member(2), _Member(3, bot=True), _Member(4, bot=True)]
    role = _Role()
    me = SimpleNamespace(guild_permissions=SimpleNamespace(manage_roles=True),
                         top_role=_Role(position=5))
    guild = SimpleNamespace(
        me=me, member_count=4, members=members,
        fetch_members=lambda limit=None: _all_members(members),
    )
    ctx = SimpleNamespace(guild=guild, author=SimpleNamespace(id=5))
    with patch.object(server_choice_roles.panels, "envoyer", AsyncMock()):
        await server_choice_roles._massrole_all_members(None, ctx, "add", role, target)
    for member in members:
        assert member.add_roles.await_count == (1 if member.id in expected else 0)
        member.remove_roles.assert_not_awaited()


def test_massrole_slash_displays_choices_not_free_text():
    async def callback(interaction: discord.Interaction, action: str,
                       role: discord.Role, cible: str = "members"):
        return None

    command = app_commands.Command(name="mass", description="Manage roles", callback=callback)
    slash_catalog._english_options(command, "role mass")
    assert {p.display_name for p in command._params.values()} == {"action", "role", "target"}
    actions = command._params["action"].choices
    targets = command._params["cible"].choices
    assert {c.value for c in actions} == {"add", "remove"}
    assert {c.value for c in targets} == {"members", "bots", "both"}


USER_A, USER_B = 123456789012345678, 223456789012345678


def test_bot_export_parses_money_xp_levels_messages_and_nested_json():
    rows = bot_data_import.parse_bot_export(
        f"user_id,cash,bank,level,xp,messages,voice_seconds,reputation\n"
        f"{USER_A},1000,400,5,20,100,3600,7\n", "export.csv",
    )
    assert rows[0].total_xp == stats_service.total_xp_for(5, 20)
    assert rows[0].cash == 1000 and rows[0].messages == 100
    nested = json.dumps({"users": [
        {"discord_id": str(USER_B), "economy": {"balance": 900},
         "levels": {"level": 2, "xp": 25}, "stats": {"messages": 10}}
    ]})
    parsed = bot_data_import.parse_bot_export(nested, "old-bot.json")
    assert parsed[0].user_id == USER_B
    assert parsed[0].cash == 900
    assert parsed[0].total_xp == stats_service.total_xp_for(2, 25)
    with pytest.raises(bot_data_import.ImportErrorData):
        bot_data_import.parse_bot_export(
            f"user_id,cash\n{USER_A},-10\n", "broken.csv",
        )
    with pytest.raises(bot_data_import.ImportErrorData):
        bot_data_import.parse_bot_export(
            f"user_id,cash\n{USER_A},10\n{USER_A},30\n", "duplicate.csv",
        )


@pytest.mark.asyncio
async def test_migration_is_atomic_deduplicated_and_preserves_missing_fields():
    with tempfile.TemporaryDirectory() as folder:
        dbpath = str(Path(folder) / "guild.sqlite")
        db = sqlite3.connect(dbpath)
        db.executescript("""
            CREATE TABLE economy (
                guild_id INTEGER, user_id INTEGER, cash INTEGER DEFAULT 0,
                bank INTEGER DEFAULT 0, last_daily INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );
            CREATE TABLE levels (
                guild_id INTEGER, user_id INTEGER, xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 0, last_message_time INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );
            CREATE TABLE message_counts (
                guild_id INTEGER, user_id INTEGER, count INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );
            CREATE TABLE voice_totals (
                guild_id INTEGER, user_id INTEGER, seconds INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );
            CREATE TABLE profiles (
                guild_id INTEGER, user_id INTEGER, reputation INTEGER DEFAULT 0,
                bio TEXT, PRIMARY KEY (guild_id, user_id)
            );
        """)
        db.execute(
            "INSERT INTO economy (guild_id,user_id,cash,bank,last_daily) "
            "VALUES (1,?,100,15,555)", (USER_A,),
        )
        db.commit()
        db.close()
        bot = SimpleNamespace(db=SimpleNamespace(path=dbpath, backend="sqlite"))
        data = bot_data_import.parse_bot_export(
            f"user_id,cash,level,xp,messages,voice_seconds,reputation\n"
            f"{USER_A},200,3,45,30,650,8\n"
            f"{USER_B},1000,4,20,44,780,9\n",
            "external.csv",
        )
        assert await bot_data_import.apply_bot_import(
            bot, 1, USER_A, data, "replace", "external.csv"
        ) == 2
        with pytest.raises(bot_data_import.ImportErrorData, match="déjà"):
            await bot_data_import.apply_bot_import(
                bot, 1, USER_A, data, "add", "external.csv",
            )

        conn = sqlite3.connect(dbpath)
        assert conn.execute(
            "SELECT cash,bank,last_daily FROM economy WHERE user_id=?",
            (USER_A,),
        ).fetchone() == (200, 15, 555)
        assert conn.execute(
            "SELECT level,xp,last_message_time FROM levels WHERE user_id=?",
            (USER_A,),
        ).fetchone() == (3, 45, 0)
        assert conn.execute(
            "SELECT count FROM message_counts WHERE user_id=?", (USER_A,),
        ).fetchone()[0] == 30
        assert conn.execute(
            "SELECT seconds FROM voice_totals WHERE user_id=?", (USER_A,),
        ).fetchone()[0] == 650
        assert conn.execute(
            "SELECT reputation FROM profiles WHERE user_id=?", (USER_A,),
        ).fetchone()[0] == 8

        too_large = [bot_data_import.ImportedMember(USER_A, cash=bot_data_import.MAX_BALANCE)]
        with pytest.raises(bot_data_import.ImportErrorData):
            await bot_data_import.apply_bot_import(
                bot, 1, USER_A, too_large, "add", "overflow.csv",
            )
        assert conn.execute(
            "SELECT COUNT(*) FROM bot_migration_batches"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT cash FROM economy WHERE user_id=?", (USER_A,),
        ).fetchone()[0] == 200
        conn.close()
