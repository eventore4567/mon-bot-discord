"""Suppression des seuls vrais doublons / sans supprimer leurs commandes +."""
from types import SimpleNamespace

import discord
from discord import app_commands

from cogs.slash_command_budget import _drop_exact_duplicate_group_leaves


async def legacy_a(interaction: discord.Interaction):
    return None


async def legacy_b(interaction: discord.Interaction):
    return None


def test_same_source_removes_longer_alias_in_same_group():
    legacy_a._sentrix_original_command = "module action"
    group = app_commands.Group(name="admin", description="Admin")
    group.add_command(app_commands.Command(name="action", description="Action", callback=legacy_a))
    group.add_command(app_commands.Command(name="module-action", description="Action alias", callback=legacy_a))
    tree = SimpleNamespace(get_commands=lambda **kw: [group])
    assert _drop_exact_duplicate_group_leaves(tree) == 1
    assert [c.name for c in group.commands] == ["action"]


def test_different_sources_are_never_deleted():
    legacy_a._sentrix_original_command = "module first"
    legacy_b._sentrix_original_command = "module second"
    group = app_commands.Group(name="tools", description="Tools")
    group.add_command(app_commands.Command(name="first", description="First", callback=legacy_a))
    group.add_command(app_commands.Command(name="second", description="Second", callback=legacy_b))
    tree = SimpleNamespace(get_commands=lambda **kw: [group])
    assert _drop_exact_duplicate_group_leaves(tree) == 0
    assert len(group.commands) == 2
