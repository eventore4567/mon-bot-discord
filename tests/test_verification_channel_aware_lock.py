"""Protection contextuelle des catégories : staff, logs, portails et membres."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from utils.verification_access_intelligence import plan_access, tokens
from sentrix_verification_v96 import VerificationConfigV96


class Role:
    def __init__(self, name, id, *, staff=False):
        self.name, self.id = name, id
        self.permissions = SimpleNamespace(
            administrator=False, manage_guild=False,
            manage_channels=staff, ban_members=False, kick_members=False,
        )


class Surface:
    def __init__(self, id, name, *, category=None, public=True, roles=()):
        self.id, self.name = id, name
        self.category, self.public = category, public
        self.overwrites = {
            role: discord.PermissionOverwrite(view_channel=True) for role in roles
        }
        self.set_permissions = AsyncMock()

    def permissions_for(self, _role):
        return SimpleNamespace(view_channel=self.public)

    def overwrites_for(self, role):
        return self.overwrites.get(role, discord.PermissionOverwrite())


def guild_screenshot():
    everyone = Role("@everyone", 1)
    staff = Role("Responsable Modérateur", 2, staff=True)
    verified = Role("Vérifié", 3)
    security = Surface(11, "🛡️ • Sécurité SentriX")
    verification_category = Surface(12, "SentriX • Vérification")
    staff_category = Surface(13, "Administration & STAFF")
    community = Surface(14, "Espace membres")
    verify = Surface(101, "✅ • verification", category=security)
    muted = Surface(102, "🚨 • stay-muted", category=security)
    auto = Surface(103, "verification-auto", category=verification_category)
    staff_room = Surface(104, "discussion", category=staff_category, roles=[staff])
    logs = Surface(105, "logs-dossiers", public=True, roles=[staff])
    renamed_log = Surface(106, "chat", public=True, roles=[staff])
    private = Surface(107, "salon-prive", public=False)
    chat = Surface(108, "general", category=community)
    unknown = Surface(109, "nouveautes")
    guild = SimpleNamespace(
        id=444, default_role=everyone,
        categories=[security, verification_category, staff_category, community],
        channels=[
            security, verification_category, staff_category, community,
            verify, muted, auto, staff_room, logs, renamed_log, private, chat, unknown,
        ],
    )
    return guild, verified, verify, {
        "security": security, "verify": verify, "muted": muted, "auto": auto,
        "staff_room": staff_room, "logs": logs, "renamed_log": renamed_log,
        "private": private, "chat": chat, "unknown": unknown,
    }


def test_case_insensitive_and_french_tokenization():
    assert "securite" in tokens("🛡️ • Sécurité SentriX")
    assert "verification" in tokens("✅ • vérification")
    assert "logs" in tokens("#logs-dossiers")


def test_screenshot_portals_remain_visible_and_staff_logs_are_classified():
    guild, _verified, verify, c = guild_screenshot()
    plan = plan_access(
        guild, verification_channel_id=verify.id, log_ids=[106],
    )
    assert [channel.id for channel in plan.gate] == [108]
    for key in ("verify", "muted", "auto", "staff_room", "logs", "renamed_log", "private"):
        assert c[key].id in plan.protected
    assert {channel.id for channel in plan.secure_sensitive} == {104, 105, 106}
    assert c["unknown"].id in plan.untouched
    assert "logs" in plan.preview().lower()
    assert c["renamed_log"] in plan.log_destinations
    assert c["logs"] in plan.suspected_logs
    assert c["staff_room"] in plan.staff_channels


def test_sensitive_channel_without_staff_role_is_not_locked_blindly():
    guild, _verified, verify, c = guild_screenshot()
    # Rôle staff absent : ne pas casser l'accès des collaborateurs.
    c["logs"].overwrites.clear()
    plan = plan_access(guild, verification_channel_id=verify.id)
    assert c["logs"] in plan.sensitive_public
    assert c["logs"] not in plan.secure_sensitive
    assert "Vérifiez" in plan.preview()


def test_configured_log_id_wins_over_public_general_name():
    guild, _verified, verify, c = guild_screenshot()
    plan = plan_access(guild, verification_channel_id=verify.id, log_ids=[106])
    assert c["renamed_log"] not in plan.gate
    assert c["renamed_log"] in plan.secure_sensitive


@pytest.mark.asyncio
async def test_real_apply_does_not_open_staff_or_logs_to_verified_role():
    guild, verified, verify, c = guild_screenshot()

    async def fetchall(sql, _args):
        assert "log_config" in sql
        return [{"channel_id": 106}]

    bot = SimpleNamespace(db=SimpleNamespace(
        get_guild_config=AsyncMock(return_value={
            "verification_channel": verify.id,
            "verify_role": verified.id,
        }),
        fetchall=AsyncMock(side_effect=fetchall),
        fetchone=AsyncMock(return_value=None),
    ))
    manager = VerificationConfigV96(bot)
    changed, protected = await manager._apply_auto_access(
        guild, verification_channel=verify,
        verified_role=verified, actor=SimpleNamespace(id=900),
    )
    assert changed >= 4
    assert protected >= 7
    member_targets = [call.args[0].id for call in c["chat"].set_permissions.await_args_list]
    assert member_targets == [guild.default_role.id, verified.id]
    for key in ("logs", "renamed_log", "staff_room"):
        targets = [call.args[0].id for call in c[key].set_permissions.await_args_list]
        assert targets == [guild.default_role.id, verified.id], key
        assert all(
            call.kwargs["overwrite"].view_channel is False
            for call in c[key].set_permissions.await_args_list
        )
    for key in ("muted", "auto", "private", "unknown"):
        c[key].set_permissions.assert_not_awaited()
    # Le salon de règlement n'est jamais fermé aux nouveaux membres.
    assert c["verify"].set_permissions.await_args_list[0].kwargs["overwrite"].view_channel is True


@pytest.mark.asyncio
async def test_db_configured_logs_are_protected_even_when_renamed():
    guild, _verified, verify, c = guild_screenshot()
    bot = SimpleNamespace(db=SimpleNamespace(
        get_guild_config=AsyncMock(return_value={}),
        fetchall=AsyncMock(return_value=[{"channel_id": 106}]),
        fetchone=AsyncMock(return_value=None),
    ))
    plan = await VerificationConfigV96(bot)._access_plan(
        guild, verification_channel=verify,
    )
    assert c["renamed_log"] in plan.secure_sensitive


@pytest.mark.asyncio
async def test_verified_role_with_staff_permissions_is_rejected(monkeypatch):
    import cogs.verification as verification
    monkeypatch.setattr(verification, "role_grant_problem", lambda _guild, _role: None)
    verified = Role("Vérifié", 33)
    verified.permissions.administrator = True
    member_bot = SimpleNamespace(guild_permissions=SimpleNamespace(
        manage_channels=True, manage_roles=True,
    ))
    guild = SimpleNamespace(me=member_bot)
    channel = SimpleNamespace(permissions_for=lambda _member: SimpleNamespace(
        view_channel=True, send_messages=True, embed_links=True,
    ))
    issues = await VerificationConfigV96(SimpleNamespace())._preflight(
        guild, channel=channel, role=verified, auto_access=False,
    )
    assert any("permissions staff" in issue for issue in issues)


def test_staff_access_inherited_from_synchronized_category_is_recognized():
    from utils.verification_access_intelligence import has_explicit_staff_access
    guild, _verified, verify, _c = guild_screenshot()
    staff = Role("Modérateur", 41, staff=True)
    category = Surface(999, "Personnel")
    category.overwrites[staff] = discord.PermissionOverwrite(view_channel=True)
    channel = Surface(1000, "logs-archives", category=category, public=True)
    channel.permissions_synced = True
    guild.categories.append(category)
    guild.channels.extend([category, channel])
    assert has_explicit_staff_access(channel, guild.default_role)
    plan = plan_access(guild, verification_channel_id=verify.id)
    assert channel in plan.secure_sensitive


def test_unsynchronized_category_does_not_prove_staff_can_read_channel():
    from utils.verification_access_intelligence import has_explicit_staff_access
    guild, _verified, verify, _c = guild_screenshot()
    staff = Role("Modérateur", 41, staff=True)
    category = Surface(999, "Personnel")
    category.overwrites[staff] = discord.PermissionOverwrite(view_channel=True)
    channel = Surface(1000, "logs-archives", category=category, public=True)
    channel.permissions_synced = False
    guild.categories.append(category)
    guild.channels.extend([category, channel])
    assert not has_explicit_staff_access(channel, guild.default_role)
    plan = plan_access(guild, verification_channel_id=verify.id)
    assert channel in plan.sensitive_public
    assert channel not in plan.secure_sensitive


def test_private_staff_channel_with_stale_verified_allow_is_not_assumed_safe():
    guild, verified, verify, c = guild_screenshot()
    leaked = Surface(
        120, "staff-confidentiel", public=False, roles=[verified],
    )
    guild.channels.append(leaked)
    plan = plan_access(
        guild, verification_channel_id=verify.id, verified_role=verified,
    )
    assert leaked.id in plan.protected
    assert leaked in plan.secure_sensitive
    assert leaked not in plan.gate
    assert "Accès staff/logs à sécuriser" in plan.preview()
    assert "Attention : -" not in plan.preview()


def test_private_staff_channel_without_verified_allow_is_left_alone():
    guild, verified, verify, c = guild_screenshot()
    private = Surface(120, "staff-confidentiel", public=False)
    guild.channels.append(private)
    plan = plan_access(
        guild, verification_channel_id=verify.id, verified_role=verified,
    )
    assert private.id in plan.protected
    assert private not in plan.secure_sensitive


def test_inherited_verified_allow_on_synced_sensitive_category_requires_denial():
    guild, verified, verify, c = guild_screenshot()
    category = Surface(140, "Staff - archives")
    category.overwrites[verified] = discord.PermissionOverwrite(view_channel=True)
    leaked = Surface(141, "archives", category=category, public=False)
    leaked.permissions_synced = True
    guild.categories.append(category)
    guild.channels.extend([category, leaked])
    plan = plan_access(
        guild, verification_channel_id=verify.id, verified_role=verified,
    )
    assert leaked in plan.secure_sensitive


@pytest.mark.asyncio
async def test_real_permission_application_revokes_old_verified_access_to_private_logs():
    guild, verified, verify, c = guild_screenshot()
    leaked = Surface(
        120, "logs-secrets", public=False, roles=[verified],
    )
    guild.channels.append(leaked)
    bot = SimpleNamespace(db=SimpleNamespace(
        get_guild_config=AsyncMock(return_value={
            "verification_channel": verify.id,
            "verify_role": verified.id,
        }),
        fetchall=AsyncMock(return_value=[]),
        fetchone=AsyncMock(return_value=None),
    ))
    await VerificationConfigV96(bot)._apply_auto_access(
        guild, verification_channel=verify, verified_role=verified,
        actor=SimpleNamespace(id=900),
    )
    revoked = {
        call.args[0].id: call.kwargs["overwrite"].view_channel
        for call in leaked.set_permissions.await_args_list
    }
    assert revoked[verified.id] is False
    assert revoked[guild.default_role.id] is False
