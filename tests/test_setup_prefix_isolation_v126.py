"""Régressions: indépendance des préfixes, setup privé et permissions."""
from __future__ import annotations

import ast
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
ROOT = Path(__file__).resolve().parents[1]


class MemoryDB:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.config = {}

    async def execute(self, sql, params=()):
        return self.conn.execute(sql, params)

    async def fetchone(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()

    async def fetchall(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    async def get_guild_config(self, guild_id):
        return {"prefix": self.config.get(guild_id, "+")}

    async def set_guild_config(self, guild_id, name, value):
        assert name == "prefix"
        self.config[guild_id] = value


@pytest.mark.asyncio
async def test_separate_prefixes_and_non_destructive_migration():
    from utils.command_prefixes import (
        get_custom_prefix, set_official_prefix, set_custom_prefix, validate_prefix,
    )
    db = MemoryDB()
    db.config[42] = "!"
    bot = SimpleNamespace(db=db, prefix_cache={})
    assert await get_custom_prefix(bot, 42) == "!"  # existing custom triggers survive
    assert await set_official_prefix(bot, 42, "$") == "$"
    assert bot.prefix_cache[42] == "$"
    assert db.config[42] == "$"
    assert await get_custom_prefix(bot, 42) == "!"
    assert await set_custom_prefix(bot, 42, "?") == "?"
    assert db.config[42] == "$"
    assert await get_custom_prefix(bot, 42) == "?"
    for invalid in ("", " ", "/", "a b", "<@123>", "abcdef"):
        with pytest.raises(ValueError):
            validate_prefix(invalid)


def test_global_native_and_custom_routing_are_isolated():
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    native = main.split("async def get_prefix(", 1)[1].split("class BotAllInOne", 1)[0]
    assert "when_mentioned_or(str(cached))" in native
    assert "when_mentioned_or(*prefixes)" not in native
    platform = (ROOT / "cogs/platform_v4.py").read_text(encoding="utf-8")
    listener = platform.split("async def on_message(self, message:", 1)[1]
    assert "get_custom_prefix(self.bot, message.guild.id)" in listener
    assert "matched = prefix if message.content.startswith(prefix) else None" in listener
    assert "if self.bot.get_command(name):" in listener


def test_private_setup_entrypoint_and_admin_custom_management():
    access = (ROOT / "utils/access_matrix.py").read_text(encoding="utf-8")
    guard = (ROOT / "cogs/permission_guard.py").read_text(encoding="utf-8")
    assert 'policy="setup:entrypoint-only"' in access
    assert '"customcmd:administrator"' in access
    assert 'if name == "setup":' in guard
    assert "return None" in guard
    inv = (ROOT / "cogs/setup_invitations.py").read_text(encoding="utf-8")
    assert "return await panels.envoyer(target, view, ephemere=True)" in inv
    v95 = (ROOT / "sentrix_v95_runtime.py").read_text(encoding="utf-8")
    assert "await interaction.response.defer(ephemeral=True, thinking=True)" in v95
    control = (ROOT / "cogs/setup_control_center.py").read_text(encoding="utf-8")
    assert "Tu n'as pas la permission d'utiliser /setup" in control
    custom = (ROOT / "cogs/setup_custom_commands.py").read_text(encoding="utf-8")
    assert "async def build_prefix_page" in custom
    assert "set_custom_prefix(" in custom
    assert "set_official_prefix(" in custom


def test_setup_has_no_member_or_role_delegation():
    control = (ROOT / "cogs/setup_control_center.py").read_text(encoding="utf-8")
    view = (ROOT / "cogs/setup_experience_v74.py").read_text(encoding="utf-8")
    assert "SETUP_DELEGATES_SCHEMA" not in control
    assert "_is_setup_delegate" not in control
    assert "_set_setup_delegate" not in control
    assert "setup_access" not in view
    assert "_build_setup_access" not in view
    assert "RoleSelect(placeholder=\"Autoriser un rôle\"" not in view
    assert "UserSelect(placeholder=\"Autoriser un membre\"" not in view
    assert "Tu n'as pas la permission d'utiliser /setup" in control


def test_dashboard_persists_both_prefixes_separately():
    dashboard = (ROOT / "web/dashboard.py").read_text(encoding="utf-8")
    assert '"custom_prefix": (1, 5)' in dashboard
    assert 'await set_custom_prefix(bot, guild_id, value)' in dashboard
    assert 'await set_official_prefix(bot, guild_id, value)' in dashboard
    assert '"custom_prefix",label:"Préfixe des commandes personnalisées"' in dashboard
    for path in (
        "main.py", "utils/access_matrix.py", "cogs/setup_custom_commands.py",
        "cogs/setup_experience_v74.py", "cogs/setup_control_center.py",
        "web/dashboard.py", "web/dashboard_oxyde_hotfix.py",
        "utils/command_prefixes.py", "web/platform_v4.py",
    ):
        ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)



@pytest.mark.asyncio
async def test_passive_vision_survives_legacy_reply_signature():
    from cogs.ai import Ai, _PASSIVE_IMAGE_CONTEXT
    author = SimpleNamespace(id=123, display_name="Membre")
    channel = SimpleNamespace(
        id=456, guild=SimpleNamespace(id=789), send=AsyncMock()
    )
    fake = SimpleNamespace(
        histories={}, ask_ai=AsyncMock(return_value="Je vois un panneau.")
    )
    token = _PASSIVE_IMAGE_CONTEXT.set(("data:image/jpeg;base64,ZGF0YQ==",))
    try:
        with patch("cogs.ai._images_from_discord_attachments", AsyncMock(return_value=[])):
            await Ai.send_sentrix_reply(fake, channel, author, "Décris cette image")
    finally:
        _PASSIVE_IMAGE_CONTEXT.reset(token)
    assert fake.ask_ai.await_args.kwargs["image_urls"] == [
        "data:image/jpeg;base64,ZGF0YQ=="
    ]
    channel.send.assert_awaited()



@pytest.mark.asyncio
async def test_custom_commands_are_silent_until_admin_allows_roles_or_members():
    from cogs.platform_v4 import PlatformV4, SCHEMA

    db = MemoryDB()
    for query in SCHEMA.split(";"):
        if query.strip():
            await db.execute(query.strip())
    await db.execute(
        "INSERT INTO platform_custom_commands "
        "(id, guild_id, name, response, created_at, updated_at) "
        "VALUES (42, 77, 'bienvenue', 'Bonjour', 0, 0)"
    )

    def member(uid, *, admin=False, roles=()):
        return SimpleNamespace(
            id=uid, bot=False,
            roles=[SimpleNamespace(id=role) for role in roles],
            guild_permissions=SimpleNamespace(administrator=admin),
        )

    owner = member(1)
    admin = member(2, admin=True)
    role_member = member(3, roles=(123,))
    user_member = member(4)
    unknown_member = member(5)
    other_guild_member = member(6, roles=(123,))
    people = {m.id: m for m in (
        owner, admin, role_member, user_member, unknown_member,
        other_guild_member,
    )}
    roles = {123: SimpleNamespace(id=123, is_default=lambda: False)}
    guild = SimpleNamespace(
        id=77, owner_id=1,
        get_member=lambda uid: people.get(uid),
        get_role=lambda rid: roles.get(rid),
    )
    bot = SimpleNamespace(db=db)
    service = PlatformV4(bot)

    assert await service.can_run_custom_command(guild, owner, 42)
    assert await service.can_run_custom_command(guild, admin, 42)
    assert not await service.can_run_custom_command(guild, role_member, 42)
    assert not await service.can_run_custom_command(guild, user_member, 42)
    assert not await service.can_run_custom_command(guild, unknown_member, 42)

    with pytest.raises(PermissionError):
        await service.set_custom_command_access(guild, 3, 42, "role", 123, enabled=True)

    await service.set_custom_command_access(
        guild, admin.id, 42, "role", 123, enabled=True
    )
    assert await service.can_run_custom_command(guild, role_member, 42)
    assert not await service.can_run_custom_command(guild, user_member, 42)
    assert not await service.can_run_custom_command(guild, unknown_member, 42)

    await service.set_custom_command_access(
        guild, admin.id, 42, "user", user_member.id, enabled=True
    )
    assert await service.can_run_custom_command(guild, user_member, 42)
    assert not await service.can_run_custom_command(guild, unknown_member, 42)

    # Les autorisations sont propres à chaque commande et chaque serveur.
    await db.execute(
        "INSERT INTO platform_custom_commands "
        "(id, guild_id, name, response, created_at, updated_at) "
        "VALUES (43, 77, 'salut', 'Salut', 0, 0)"
    )
    assert not await service.can_run_custom_command(guild, role_member, 43)

    await service.set_custom_command_access(
        guild, owner.id, 42, "everyone", 0, enabled=True
    )
    assert await service.can_run_custom_command(guild, unknown_member, 42)
    await service.set_custom_command_access(
        guild, owner.id, 42, "everyone", 0, enabled=False
    )
    assert not await service.can_run_custom_command(guild, unknown_member, 42)

    await service.set_custom_command_access(
        guild, admin.id, 42, "role", 123, enabled=False
    )
    assert not await service.can_run_custom_command(guild, role_member, 42)

    await service.delete_custom_command(guild.id, admin.id, 42)
    assert await service.list_custom_command_access(guild.id, 42) == []


def test_custom_command_access_checks_before_any_side_effect():
    platform = (ROOT / "cogs/platform_v4.py").read_text(encoding="utf-8")
    listener = platform.split("async def on_message(self, message:", 1)[1]
    decision = listener.index("if not await self.can_run_custom_command(")
    actions = listener.index("await custom_commands.executer_actions(")
    deletion = listener.index("await message.delete()")
    response = listener.index("await message.channel.send(")
    assert decision < actions < deletion < response

    view = (ROOT / "cogs/setup_custom_commands.py").read_text(encoding="utf-8")
    assert "class CustomCommandAccessView(discord.ui.View)" in view
    assert 'placeholder="Autoriser un rôle à lancer la commande"' in view
    assert 'placeholder="Autoriser un membre à lancer la commande"' in view
    assert 'label="Qui peut utiliser ?"' in view
    assert "ephemeral=True" in view
    assert "class CustomCommandAccessView" in view
    assert "async def _build_setup_access" not in (
        ROOT / "cogs/setup_experience_v74.py"
    ).read_text(encoding="utf-8")
