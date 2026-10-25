"""Verification must lock eligible voice channels as well as member text channels.

Tests use in-memory Discord permissions and do not touch any server.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from sentrix_verification_v96 import VerificationConfigV96
from utils.verification_access_intelligence import is_voice_channel, plan_access


class Role:
    def __init__(self, role_id, name):
        self.id = role_id
        self.name = name


class Channel:
    def __init__(self, channel_id, name, *, kind="text", public=True,
                 can_connect=True, category=None, synced=False):
        self.id = channel_id
        self.name = name
        self.type = kind
        self.category = category
        self.category_id = category.id if category else None
        self.permissions_synced = synced
        self.public = public
        self.can_connect = can_connect
        self.overwrites = {}
        self.updated = []

    def permissions_for(self, _role):
        return SimpleNamespace(
            view_channel=self.public, connect=self.can_connect,
            manage_channels=True,
        )

    def overwrites_for(self, role):
        return self.overwrites.get(role, discord.PermissionOverwrite())

    async def set_permissions(self, role, *, overwrite=None, reason=None):
        self.updated.append((role.id, overwrite, reason))
        if overwrite is None:
            self.overwrites.pop(role, None)
        else:
            self.overwrites[role] = overwrite


def fixtures(*channels, categories=()):
    everyone = Role(1, "@everyone")
    verified = Role(2, "Vérifié")
    member = Role(3, "SentriX")
    guild = SimpleNamespace(
        default_role=everyone, me=member,
        channels=[*categories, *channels], categories=list(categories),
    )
    return guild, everyone, verified


def test_member_text_and_voice_are_detected_but_logs_stay_protected():
    text = Channel(10, "général")
    voice = Channel(11, "Général", kind="voice")
    logs = Channel(12, "logs-messages", public=False)
    guild, everyone, verified = fixtures(text, voice, logs)
    plan = plan_access(guild, verification_channel_id=13,
                       log_ids=[12], verified_role=verified)
    assert [ch.id for ch in plan.gate] == [10, 11]
    assert logs.id in plan.protected
    preview = plan.preview()
    assert "Salons textuels à verrouiller : 1" in preview
    assert "Vocaux à verrouiller : 1" in preview
    assert "logs-messages" not in preview


def test_already_private_or_connect_denied_voice_is_not_opened():
    hidden = Channel(21, "Général", kind="voice", public=False)
    denied = Channel(22, "General", kind="voice", can_connect=False)
    guild, _, verified = fixtures(hidden, denied)
    plan = plan_access(guild, verification_channel_id=99, verified_role=verified)
    assert not plan.gate
    assert [x.id for x in plan.voice_already_locked] == [21, 22]
    assert "Vocaux déjà restreints : 2" in plan.preview()


def test_staff_voice_is_never_selected_even_when_public():
    voice = Channel(31, "Général", kind="voice")
    voice.category = Channel(30, "STAFF", kind="category")
    voice.category_id = 30
    guild, _, verified = fixtures(voice, categories=[voice.category])
    plan = plan_access(guild, verification_channel_id=99, verified_role=verified)
    assert not plan.gate
    assert 31 in plan.protected


@pytest.mark.asyncio
async def test_confirmation_locks_connect_and_view_only_on_member_voice():
    member_voice = Channel(41, "Général", kind="voice")
    member_text = Channel(42, "général")
    staff_voice = Channel(43, "Staff vocal", kind="voice")
    guild, everyone, verified = fixtures(member_voice, member_text, staff_voice)
    plan = plan_access(guild, verification_channel_id=99, verified_role=verified)
    assert staff_voice not in plan.gate
    manager = VerificationConfigV96(SimpleNamespace())
    manager._access_plan = AsyncMock(return_value=plan)
    portal = Channel(99, "règlement")
    changed, protected = await manager._apply_auto_access(
        guild, verification_channel=portal, verified_role=verified,
        actor=SimpleNamespace(id=10),
    )
    assert changed == 2
    assert protected >= 1
    assert member_voice.overwrites[everyone].view_channel is False
    assert member_voice.overwrites[everyone].connect is False
    assert member_voice.overwrites[verified].view_channel is True
    assert member_voice.overwrites[verified].connect is True
    assert member_text.overwrites[everyone].view_channel is False
    assert member_text.overwrites[verified].view_channel is True
    assert member_text.overwrites[everyone].connect is None
    assert not staff_voice.updated
    assert is_voice_channel(member_voice) is True
    assert is_voice_channel(member_text) is False


@pytest.mark.asyncio
async def test_sync_category_keeps_children_synced_and_locks_voice():
    cat = Channel(60, "Salons vocaux", kind="category")
    voice = Channel(61, "Général", kind="voice", category=cat, synced=True)
    guild, everyone, verified = fixtures(voice, categories=[cat])
    plan = plan_access(guild, verification_channel_id=99, verified_role=verified)
    assert cat in plan.category_gates
    manager = VerificationConfigV96(SimpleNamespace())
    manager._access_plan = AsyncMock(return_value=plan)
    changed, _ = await manager._apply_auto_access(
        guild, verification_channel=Channel(99, "règlement"),
        verified_role=verified, actor=SimpleNamespace(id=11),
    )
    assert changed == 1
    assert cat.overwrites[everyone].connect is False
    assert cat.overwrites[verified].connect is True
    assert not voice.updated


@pytest.mark.asyncio
async def test_existing_connect_deny_is_not_overridden_for_private_voice():
    voice = Channel(71, "Général", kind="voice", can_connect=False)
    guild, everyone, verified = fixtures(voice)
    plan = plan_access(guild, verification_channel_id=99, verified_role=verified)
    manager = VerificationConfigV96(SimpleNamespace())
    manager._access_plan = AsyncMock(return_value=plan)
    changed, _ = await manager._apply_auto_access(
        guild, verification_channel=Channel(99, "règlement"),
        verified_role=verified, actor=SimpleNamespace(id=11),
    )
    assert changed == 0
    assert not voice.updated


def test_onboarding_default_and_prompt_channels_are_excluded():
    member_voice = Channel(80, "Général", kind="voice")
    onboarding_member = Channel(81, "boosters")
    logs = Channel(82, "logs-messages")
    guild, _, verified = fixtures(member_voice, onboarding_member, logs)
    plan = plan_access(
        guild, verification_channel_id=99,
        onboarding_ids=[81], log_ids=[82], verified_role=verified,
    )
    assert [ch.id for ch in plan.gate] == [80]
    assert plan.protected[81] == "portail/configuration enregistrée"
    assert 82 in plan.protected


@pytest.mark.asyncio
async def test_onboarding_loader_protects_default_channels_and_prompt_choices():
    bot = SimpleNamespace()
    cog = VerificationConfigV96(bot)
    guild = SimpleNamespace(
        onboarding=AsyncMock(return_value=SimpleNamespace(
            enabled=False,
            default_channels=[SimpleNamespace(id=121)],
            prompts=[
                SimpleNamespace(options=[
                    SimpleNamespace(channels=[SimpleNamespace(id=122)]),
                    SimpleNamespace(channels=[SimpleNamespace(id=123)]),
                ]),
            ],
        )),
        rules_channel=SimpleNamespace(id=124),
        public_updates_channel=None,
    )
    assert await cog._onboarding_protected_ids(guild) == {121, 122, 123, 124}


@pytest.mark.asyncio
async def test_onboarding_350003_does_not_abort_other_member_voice_locks():
    locked_by_discord = Channel(131, "boosters")
    voice = Channel(132, "Général", kind="voice")
    guild, everyone, verified = fixtures(locked_by_discord, voice)
    plan = plan_access(guild, verification_channel_id=99, verified_role=verified)

    async def discord_rejects_onboarding(role, *, overwrite=None, reason=None):
        if role is everyone:
            response = SimpleNamespace(status=400, reason="Bad Request")
            raise discord.HTTPException(
                response,
                {"code": 350003, "message": "Onboarding channels must be readable by everyone"},
            )
        raise AssertionError("Must not add verified-role access to an onboarding channel")

    locked_by_discord.set_permissions = discord_rejects_onboarding
    manager = VerificationConfigV96(SimpleNamespace())
    manager._access_plan = AsyncMock(return_value=plan)
    changed, protected = await manager._apply_auto_access(
        guild, verification_channel=Channel(99, "règlement"),
        verified_role=verified, actor=SimpleNamespace(id=5),
    )
    assert changed == 1
    assert protected >= 1
    assert voice.overwrites[everyone].connect is False
    assert voice.overwrites[verified].connect is True
    assert not locked_by_discord.overwrites
