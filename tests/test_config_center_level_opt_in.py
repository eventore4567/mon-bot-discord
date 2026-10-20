"""Contrats : /config dédié et annonces de niveaux uniquement après opt-in."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import setup_control_center, setup_v2_core
from cogs.levels import Levels, BoolToggleButton
from database.db import DEFAULT_STATS_SETTINGS


EXPECTED_CONFIG = {
    "accueil", "automod", "logs", "surveillance", "tickets",
    "bienvenue", "moderation", "niveaux", "diagnostic",
}


def test_grouped_slash_config_has_surveillance_and_all_nine_sections():
    group = setup_control_center.OfficialSetup.config_group
    assert group.name == "config"
    assert {cmd.name for cmd in group.commands} == EXPECTED_CONFIG
    assert "setup" not in {c.name for c in setup_control_center.OfficialSetup.__cog_app_commands__}
    assert set(setup_control_center.CATEGORIES) >= {
        "security", "logs", "tickets", "welcome", "moderation", "levels",
    }


def test_setting_level_channel_does_not_implicitly_start_xp():
    assert "level_channel" not in setup_v2_core.GUILD_CONFIG_FIELD_MODULE


def test_default_level_announcements_are_off_without_explicit_staff_opt_in():
    assert DEFAULT_STATS_SETTINGS["level_announce_enabled"] is False
    assert DEFAULT_STATS_SETTINGS["level_announce_opt_in"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "settings,expected",
    [
        ({"level_announce_enabled": True}, False),  # ancienne valeur implicite
        ({"level_announce_enabled": False, "level_announce_opt_in": True}, False),
        ({"level_announce_enabled": True, "level_announce_opt_in": False}, False),
        ({"level_announce_enabled": True, "level_announce_opt_in": True}, True),
    ],
)
async def test_level_up_sends_only_if_staff_explicitly_activated(settings, expected):
    cog = Levels.__new__(Levels)
    cog.bot = SimpleNamespace(db=SimpleNamespace())
    cog._apply_xp_delta = AsyncMock(return_value=(5, 1, True))
    cog._send_level_announcement = AsyncMock(return_value=True)
    cog._assign_level_role = AsyncMock()
    guild = SimpleNamespace(id=1, get_channel=lambda _: None)
    member = SimpleNamespace(id=2)
    message = SimpleNamespace(guild=guild, author=member, channel=SimpleNamespace(id=3))
    with patch("cogs.levels.temporary_boosts.apply_xp_boost", AsyncMock(return_value=(10, None))):
        await cog._process_xp(
            message, {"xp_min": 10, "xp_max": 10, **settings},
            {"xp_multiplier": 1.0, "level_channel": None},
        )
    if expected:
        cog._send_level_announcement.assert_awaited_once()
    else:
        cog._send_level_announcement.assert_not_awaited()
    cog._assign_level_role.assert_awaited_once()


def test_statsconfig_toggle_requires_a_fresh_explicit_click():
    owner = SimpleNamespace(pending={
        "level_announce_enabled": True,
        "level_announce_opt_in": False,
    })
    button = BoolToggleButton(owner, "level_announce_enabled", "Annonce", row=3)
    assert "Non" in button.label


@pytest.mark.asyncio
async def test_statsconfig_toggle_sets_opt_in_in_pending_settings():
    owner = SimpleNamespace(pending={
        "level_announce_enabled": True,
        "level_announce_opt_in": False,
    }, refresh=AsyncMock())
    button = BoolToggleButton(owner, "level_announce_enabled", "Annonce", row=3)
    await button.callback(SimpleNamespace())
    assert owner.pending["level_announce_enabled"] is True
    assert owner.pending["level_announce_opt_in"] is True
    owner.refresh.assert_awaited_once()
