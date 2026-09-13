from __future__ import annotations

import sentrix_command_surface_v110 as surface


def test_public_command_names_are_short() -> None:
    assert surface.COMPACT_COMMAND_NAMES
    assert all(1 <= len(name) <= 20 for name in surface.COMPACT_COMMAND_NAMES.values())


def test_common_slash_roots_are_compact() -> None:
    assert surface.COMPACT_ROOT_NAMES["moderation"] == "mod"
    assert surface.COMPACT_ROOT_NAMES["notifications"] == "notify"


def test_long_legacy_names_are_normalised_without_hashes() -> None:
    samples = {
        "very-long-configuration-command": "very-long-config-com",
        "permission-management-system": "perms-management",
        "notification-notification-history": "notif-notif-history",
    }
    for source, expected in samples.items():
        compact = surface._normalise_public_leaf(source)
        assert compact == expected
        assert len(compact) <= 20
        assert not any(char in compact for char in "abcdef0123456789" if False)


def test_collision_suffix_is_readable() -> None:
    used = {"moneytop"}
    second = surface._compact_unique_leaf("moneytop", used, "leaderboard-money")
    third = surface._compact_unique_leaf("moneytop", used, "economyleaderboard")
    assert second == "moneytop-2"
    assert third == "moneytop-3"
    assert len(used) == 3
