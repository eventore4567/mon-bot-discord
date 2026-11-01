"""Mass-role UI regressions: confirmation is disabled until a target is selected."""
import discord

from cogs.role_mass_target import MassRoleView, TargetSelect


def test_bulk_role_confirmation_requires_target():
    view = MassRoleView(object(), 1, 2, 3, "add", english=False)
    selects = [item for item in view.children if isinstance(item, TargetSelect)]
    assert len(selects) == 1
    assert {option.value for option in selects[0].options} == {"members", "bots", "all"}
    buttons = [item for item in view.children if isinstance(item, discord.ui.Button)]
    assert any(item.label == "Confirmer" and item.disabled for item in buttons)
    assert any(item.label == "Annuler" for item in buttons)


def test_bulk_role_english_labels():
    view = MassRoleView(object(), 1, 2, 3, "remove", english=True)
    buttons = [item for item in view.children if isinstance(item, discord.ui.Button)]
    assert any(item.label == "Confirm" and item.disabled for item in buttons)
    assert any(item.label == "Cancel" for item in buttons)
