"""Discord AutoMod native blocking is visible to staff without content leaks."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from cogs.automod import AutoMod
from cogs import live_log_delivery_v5 as delivery


class RestrictedExecution:
    """The content of a blocked message must never be read by SentriX logs."""
    guild_id = 123
    rule_id = 456
    user_id = 789
    channel_id = 321
    message_id = 987
    action = SimpleNamespace(type=discord.AutoModRuleActionType.block_message)

    @property
    def content(self):
        raise AssertionError("Blocked content was read")

    @property
    def matched_content(self):
        raise AssertionError("Matched content was read")


@pytest.mark.asyncio
async def test_native_block_creates_one_staff_log_with_rule_channel_and_member():
    guild = SimpleNamespace(get_member=lambda user_id: None)
    bot = SimpleNamespace(get_guild=lambda guild_id: guild if guild_id == 123 else None)
    audit = AsyncMock()
    cog = SimpleNamespace(
        bot=bot,
        _native_block_last_seen={},
        _native_rule_details={(123, 456): ("SentriX anti-invitations", None)},
        log_action=audit,
    )

    await AutoMod.on_automod_action(cog, RestrictedExecution())
    audit.assert_awaited_once()
    args = audit.await_args.args
    assert args[0] is guild
    assert args[2] == "automod"
    fields = {field.name: field.value for field in args[1].fields}
    assert fields["Membre"] == "<@789>"
    assert fields["Salon"] == "<#321>"
    assert "SentriX anti-invitations" in fields["Règle"]
    assert fields["Source"] == "Discord AutoMod"
    assert "bloqué" in fields["Statut"]
    assert not any("content" in field.name.casefold() for field in args[1].fields)
    buttons = audit.await_args.kwargs["suites"].children
    assert len(buttons) == 1
    assert buttons[0].label == "Accéder au salon"
    assert buttons[0].url == "https://discord.com/channels/123/321"

    # The same user/rule event repeated within the debounce window is ignored.
    await AutoMod.on_automod_action(cog, RestrictedExecution())
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_native_automod_ignores_unrelated_and_unknown_server_events():
    audit = AsyncMock()
    bot = SimpleNamespace(get_guild=lambda _: None)
    cog = SimpleNamespace(
        bot=bot,
        _native_block_last_seen={},
        _native_rule_details={(123, 456): ("Rule", None)},
        log_action=audit,
    )
    await AutoMod.on_automod_action(cog, RestrictedExecution())
    audit.assert_not_awaited()

    other = SimpleNamespace(
        guild_id=123, rule_id=456, user_id=789, channel_id=321,
        action=SimpleNamespace(type=None),
    )
    await AutoMod.on_automod_action(cog, other)
    audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicitly_disabled_log_category_stays_disabled_without_channel(monkeypatch):
    bot = SimpleNamespace()
    guild = SimpleNamespace(id=123)
    get_setting = AsyncMock(return_value={"enabled": False, "channel_id": None})
    monkeypatch.setattr(delivery.log_service, "get_log_setting", get_setting)

    def fail_discovery(*args):
        raise AssertionError("disabled log route must never trigger auto-discovery")

    monkeypatch.setattr(delivery, "_discover_channel", fail_discovery)
    ok = await delivery.send_log_v5(
        bot, guild, "voice_move", discord.Embed(title="Déplacement vocal"),
    )
    assert ok is False
    assert bot.live_log_delivery_v5_state["last_result"] == "explicitly_disabled"


def test_missing_channel_warning_throttled_by_category():
    delivery._MISSING_CHANNEL_WARNED_AT.clear()
    assert delivery._should_warn_missing_channel(123, "voice", 1000.0)
    assert not delivery._should_warn_missing_channel(123, "voice", 1010.0)
    assert delivery._should_warn_missing_channel(123, "resources", 1010.0)
    assert delivery._should_warn_missing_channel(123, "voice", 4601.0)
    delivery._MISSING_CHANNEL_WARNED_AT.clear()
