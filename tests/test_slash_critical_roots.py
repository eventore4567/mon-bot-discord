"""Keep essential slash roots inside Discord's hard 100-command budget."""
from cogs import slash_command_budget


def test_critical_slash_commands_are_reservations():
    required = slash_command_budget._required_names()
    assert {"presentation", "play", "help", "ping", "setup"}.issubset(required)
    assert len(required) <= slash_command_budget.GLOBAL_CHAT_INPUT_BUDGET


def test_rps_is_preserved_under_play_group():
    from utils import slash_catalog
    names = {entry.path for entry in slash_catalog.CATALOG}
    assert "play" in slash_command_budget._required_names()
    assert "play rps" in names

def test_role_mass_kept_by_final_slash_group_rebuilder():
    from sentrix_command_surface_v110 import STANDARD_GROUPED_SLASH

    assert STANDARD_GROUPED_SLASH["role mass"] == ("role", "mass")
    assert STANDARD_GROUPED_SLASH["giverole"] == ("role", "give")
    assert STANDARD_GROUPED_SLASH["removerole"] == ("role", "remove")
