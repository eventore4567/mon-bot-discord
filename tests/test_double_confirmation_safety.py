from __future__ import annotations

import inspect

from cogs import member_data_retention_v17
from utils import helpers


def test_double_confirmation_helper_is_idempotent_and_two_step():
    source = inspect.getsource(helpers.double_confirm_destructive)
    assert "Première confirmation" in source
    assert "Dernière confirmation" in source
    assert "_sentrix_double_confirmed" in source
    assert source.count("ConfirmView(") == 1
    assert "for index, (title, message) in enumerate(prompts, start=1)" in source


def test_reset_invites_is_in_late_reset_guard():
    assert member_data_retention_v17.RESET_COMMAND_LABELS["reset-invites"]


def test_only_high_impact_bulk_commands_are_covered_by_late_guard():
    expected = {
        "config-reset",
        "reset-logs-all",
        "delete-channel",
        "security all",
        "create-logs",
        "syncbl",
    }
    assert expected <= set(member_data_retention_v17.DOUBLE_CONFIRM_COMMANDS)
    low_risk = {
        "logs reset",
        "chat-reset",
        "ai reset",
        "sanctiondm reset",
        "resetnick",
        "clearwarnings",
        "clear",
        "ticketpanel delete",
        "tickettype remove",
        "ticketform remove",
        "music clear",
    }
    assert not (low_risk & set(member_data_retention_v17.DOUBLE_CONFIRM_COMMANDS))
    assert "represet" not in member_data_retention_v17.RESET_COMMAND_LABELS


def test_late_guard_calls_double_confirmation_before_original_callback():
    source = inspect.getsource(member_data_retention_v17._install_destructive_confirmations)
    confirm_at = source.index("helpers.double_confirm_destructive")
    original_at = source.index("return await __original", confirm_at)
    assert confirm_at < original_at
    assert "_sentrix_double_confirmation_guard" in source


def test_reset_wrapper_also_uses_same_two_step_confirmation():
    source = inspect.getsource(member_data_retention_v17._send_reset_confirmation)
    assert "helpers.double_confirm_destructive" in source
    assert "explicit_data_reset()" in source


def test_bulk_guard_supports_standalone_commands_without_cog_self():
    source = inspect.getsource(member_data_retention_v17._install_destructive_confirmations)
    assert "async def wrapped(*args" in source
    assert "isinstance(value, commands.Context)" in source
