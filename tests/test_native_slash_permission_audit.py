"""A native slash command must remain in the real permission audit."""
import asyncio
from types import SimpleNamespace

import discord
from discord import app_commands

from tools.permission_audit_sweep import _Audit, _patch_native_command_bodies, SKIP_COMMANDS


async def native_callback(interaction: discord.Interaction):
    raise AssertionError("The audit must not call this business method")


def test_presentation_is_not_skipped_by_permission_audit():
    assert "presentation" not in SKIP_COMMANDS


def test_native_callback_is_stubbed_after_permission_dispatch():
    command = app_commands.Command(
        name="presentation",
        description="SentriX public presentation.",
        callback=native_callback,
    )
    tree = SimpleNamespace(walk_commands=lambda: iter([command]))
    bot = SimpleNamespace(tree=tree)
    _patch_native_command_bodies(bot)
    _Audit.reached = False
    asyncio.run(command._callback(None))
    assert _Audit.reached
