from types import SimpleNamespace

from cogs.command_error_release_v41 import _dedupe_prefix_error_listeners
from cogs.runtime_consistency_v57 import _normalise_prefix_duration


def test_mute_accepts_two_word_french_duration_without_reason():
    assert _normalise_prefix_duration("10", "minutes") == ("10 minutes", "Aucune raison")


def test_mute_accepts_two_word_french_duration_and_keeps_reason():
    assert _normalise_prefix_duration("2", "heures spam répété") == ("2 heures", "spam répété")


def test_mute_keeps_compact_duration_unchanged():
    assert _normalise_prefix_duration("10m", "spam") == ("10m", "spam")


def test_prefix_error_dedupe_keeps_hardening_release_listener():
    async def prefix_failed(ctx, error):
        return None

    async def obsolete_listener(ctx, error):
        return None

    prefix_failed.__module__ = "cogs.command_hardening_v41"
    obsolete_listener.__module__ = "cogs.legacy_errors"

    bot = SimpleNamespace(
        extra_events={"on_command_error": [prefix_failed, obsolete_listener]}
    )

    removed = _dedupe_prefix_error_listeners(bot)

    assert removed == 1
    assert bot.extra_events["on_command_error"] == [prefix_failed]
