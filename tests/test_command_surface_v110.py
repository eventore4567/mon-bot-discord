from __future__ import annotations

import sentrix_command_surface_v110 as surface


def test_familiar_existing_names_and_user_exceptions_are_preserved() -> None:
    assert "userinfo" not in surface.COMPACT_COMMAND_NAMES
    assert "serverinfo" not in surface.COMPACT_COMMAND_NAMES
    assert surface.STANDARD_DIRECT_SLASH["userinfo"] == "userinfo"
    assert surface.STANDARD_DIRECT_SLASH["serverinfo"] == "serverinfo"
    assert surface.STANDARD_DIRECT_SLASH["membercount"] == "members"
    assert surface.STANDARD_DIRECT_SLASH["set-bio"] == "set-bio"
    assert surface.STANDARD_DIRECT_SLASH["guess-number"] == "guess-number"
    assert surface.STANDARD_DIRECT_SLASH["setprefix"] == "setprefix"
    assert surface.STANDARD_DIRECT_SLASH["welcome-config"] == "welcome-config"


def test_core_moderation_uses_common_direct_slash_names() -> None:
    unchanged = {
        "ban", "unban", "kick", "mute", "unmute", "warn",
        "clear", "lock", "unlock", "slowmode",
    }
    for name in unchanged:
        assert surface.STANDARD_DIRECT_SLASH[name] == name
    assert surface.STANDARD_DIRECT_SLASH["warnings"] == "warns"
    assert surface.STANDARD_DIRECT_SLASH["clearwarnings"] == "clearwarns"
    assert surface.STANDARD_DIRECT_SLASH["nickname"] == "nick"


def test_info_level_and_music_use_common_names() -> None:
    assert surface.STANDARD_DIRECT_SLASH["avatar"] == "avatar"
    assert surface.STANDARD_DIRECT_SLASH["userinfo"] == "userinfo"
    assert surface.STANDARD_DIRECT_SLASH["serverinfo"] == "serverinfo"
    assert surface.STANDARD_DIRECT_SLASH["leaderboard-levels"] == "leaderboard"
    assert surface.STANDARD_DIRECT_SLASH["play"] == "play"
    assert surface.STANDARD_DIRECT_SLASH["music pause"] == "pause"
    assert surface.STANDARD_DIRECT_SLASH["music queue"] == "queue"
    assert surface.STANDARD_DIRECT_SLASH["music nowplaying"] == "nowplaying"


def test_role_management_uses_role_group() -> None:
    assert surface.STANDARD_GROUPED_SLASH["giverole"] == ("role", "give")
    assert surface.STANDARD_GROUPED_SLASH["removerole"] == ("role", "remove")
    assert surface.STANDARD_GROUPED_SLASH["roleall"] == ("role", "all")
    assert surface.STANDARD_GROUPED_SLASH["massrole"] == ("role", "mass")


def test_canonical_grouped_names_are_simple_and_stable() -> None:
    expected = {
        "economyleaderboard": ("economy", "leaderboard"),
        "ticketsetup": ("ticket", "setup"),
        "logsetup": ("logs", "setup"),
        "aidiag": ("ai", "status"),
        "server-health": ("server", "health"),
        "schedule-send": ("schedule", "send"),
        "voice-lock": ("voice", "lock"),
    }
    for source, public in expected.items():
        assert surface.CANONICAL_GROUPED_NAMES[source] == public


def test_roots_are_not_arbitrarily_abbreviated() -> None:
    assert surface.COMPACT_ROOT_NAMES == {}


def test_long_legacy_names_are_normalised_readably() -> None:
    samples = {
        "very-long-configuration-command": "very-long-config",
        "permission-management-system": "perms-management",
        "notification-notification-history": "notif-history",
    }
    for source, expected in samples.items():
        compact = surface._normalise_public_leaf(source)
        assert compact == expected
        assert len(compact) <= 20


def test_collision_suffix_is_readable() -> None:
    used = {"leaderboard"}
    second = surface._compact_unique_leaf("leaderboard", used, "legacy-one")
    third = surface._compact_unique_leaf("leaderboard", used, "legacy-two")
    assert second == "leaderboard-2"
    assert third == "leaderboard-3"
    assert len(used) == 3



def test_me_and_profile_are_not_public_direct_slash_commands() -> None:
    assert "profile" not in surface.STANDARD_DIRECT_SLASH
    assert "me" not in surface.STANDARD_DIRECT_SLASH.values()
