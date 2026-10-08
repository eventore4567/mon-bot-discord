"""Un menu contextuel Discord ne consomme pas une racine slash chat-input."""
from __future__ import annotations

import discord
from discord import app_commands

from tools.command_runtime_audit import _chat_input_roots


def test_audit_counts_only_chat_input_commands():
    client = discord.Client(intents=discord.Intents.none())
    tree = app_commands.CommandTree(client)

    @app_commands.command(name="ping", description="Check bot latency.")
    async def ping(interaction: discord.Interaction):
        return None

    @app_commands.context_menu(name="Inspect member")
    async def inspect_member(interaction: discord.Interaction, user: discord.User):
        return None

    tree.add_command(ping)
    tree.add_command(inspect_member)

    assert len(tree.get_commands()) == 2
    roots = _chat_input_roots(tree)
    assert len(roots) == 1
    assert roots[0].name == "ping"
