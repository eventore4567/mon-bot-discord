"""Keep essential slash roots inside Discord's hard 100-command budget."""
from cogs import slash_command_budget


def test_critical_slash_commands_are_reservations():
    required = slash_command_budget._required_names()
    assert {"presentation", "rps", "help", "ping", "setup"}.issubset(required)
    assert len(required) <= slash_command_budget.GLOBAL_CHAT_INPUT_BUDGET


def test_rps_is_preferred_over_optional_legacy_commands():
    assert "rps" in slash_command_budget._preferred_names()
    assert "rps" not in slash_command_budget._excluded_names()
