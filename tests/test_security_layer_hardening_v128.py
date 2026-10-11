"""Régressions des protections défensives : antispam, pièces jointes, piège, web."""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.honeypot_verification_v48 import HoneypotVerification
from cogs.security_runtime_hardening import SecurityHardening
from utils.security_duplicate_window import DuplicateMessageWindow
from web import public_verification_v120 as web_verify


def _staff(*, manage_guild=True):
    member = Mock(spec=discord.Member)
    member.id = 42
    member.bot = False
    member.guild_permissions = SimpleNamespace(
        administrator=False, manage_guild=manage_guild,
    )
    guild = SimpleNamespace(id=23, owner_id=999)
    member.guild = guild
    return member


def test_flood_tracker_detects_repetition_and_respects_timeout():
    window = DuplicateMessageWindow(max_fingerprints=8)
    assert window.add(1, 7, "HelLO \u200b world", now=100) is False
    assert window.add(1, 7, "hello world", now=103) is False
    assert window.add(1, 7, "HELLO  WORLD", now=108) is True
    assert window.add(1, 8, "HELLO WORLD", now=108) is False
    assert window.add(1, 7, "HELLO WORLD", now=150) is False


def test_flood_tracker_is_bounded_even_for_unique_rapid_messages():
    window = DuplicateMessageWindow(max_fingerprints=8)
    for n in range(700):
        assert window.add(1, 7, f"Unique spam {n}", now=1000+n/10000) is False
        assert len(window) <= 8
    assert window.add(1, 7, "hi", now=1100) is False
    assert len(window) == 0


@pytest.mark.asyncio
async def test_dangerous_attachment_detects_disguised_executable_filename():
    security_config = {"antiscam": 1, "antispam": 0, "antimention": 0}
    automod = SimpleNamespace(
        get_automod_cached=AsyncMock(return_value=security_config),
        security_filter_applies_to=AsyncMock(return_value=True),
        _delete_and_warn=AsyncMock(),
    )
    bot = SimpleNamespace(
        get_cog=lambda name: automod if name == "Automod" else None,
        loop=SimpleNamespace(call_later=Mock()),
    )
    cog = SecurityHardening(bot)
    cog._security_event = AsyncMock()
    member = _staff(manage_guild=False)
    msg = SimpleNamespace(
        id=999, guild=member.guild, author=member,
        attachments=[SimpleNamespace(filename="invoice.exe\u200b.")],
    )
    await cog.on_message(msg)
    automod._delete_and_warn.assert_awaited_once()
    assert automod._delete_and_warn.await_args.args[2] == "dangerous_attachment"
    cog._security_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_honeypot_never_kicks_or_softbans_manage_server_staff():
    member = _staff()
    msg = SimpleNamespace(
        guild=member.guild, author=member,
        channel=SimpleNamespace(id=99),
        delete=AsyncMock(),
    )
    cog = SimpleNamespace(config=AsyncMock(side_effect=AssertionError("not called")))
    await HoneypotVerification.on_message(cog, msg)
    cog.config.assert_not_awaited()
    msg.delete.assert_not_awaited()
    member.kick.assert_not_awaited() if hasattr(member.kick, "assert_not_awaited") else None


@pytest.mark.asyncio
async def test_manage_server_staff_not_forced_into_unverified_role_on_join():
    member = _staff()
    cog = SimpleNamespace(config=AsyncMock(side_effect=AssertionError("not called")))
    await HoneypotVerification.on_member_join(cog, member)
    cog.config.assert_not_awaited()


@pytest.mark.asyncio
async def test_web_verify_does_not_demote_staff_with_unverified_role():
    member = _staff()
    member.roles = []
    member.add_roles = AsyncMock()
    verified = SimpleNamespace(id=111)
    unverified = SimpleNamespace(id=222)
    member.guild.get_role = lambda role_id: {111: verified, 222: unverified}.get(role_id)
    cog = SimpleNamespace(config=AsyncMock(return_value={
        "verified_role_id": 111,
        "unverified_role_id": 222,
    }))
    bot = SimpleNamespace(get_cog=lambda name: cog)
    ok, error = await web_verify._ensure_pending_enrollment(bot, member.guild, member)
    assert ok is False
    assert error.status == 409
    assert '"staff_exempt"' in error.text
    member.add_roles.assert_not_awaited()


def test_captcha_generation_throttle_is_scoped_and_bounded():
    web_verify._challenge_issued.clear()
    assert web_verify._challenge_retry_after(1, 7, now=100) == 0
    assert web_verify._challenge_retry_after(1, 7, now=101) == 2
    assert web_verify._challenge_retry_after(1, 8, now=101) == 0
    assert web_verify._challenge_retry_after(1, 7, now=103.2) == 0
    web_verify._challenge_issued.clear()
    for i in range(web_verify._MAX_CHALLENGE_RATE_KEYS + 30):
        assert web_verify._challenge_retry_after(i + 1, 7, now=200) == 0
    assert len(web_verify._challenge_issued) <= web_verify._MAX_CHALLENGE_RATE_KEYS
    web_verify._challenge_issued.clear()
