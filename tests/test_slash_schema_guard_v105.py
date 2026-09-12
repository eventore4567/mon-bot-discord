from __future__ import annotations

import discord
import pytest
from discord import app_commands
from discord.ext import commands

import sentrix_v103_setup_fix as v103
import sentrix_v105_slash_schema_guard as v105


def _tree() -> app_commands.CommandTree:
    client = discord.Client(intents=discord.Intents.none())
    return app_commands.CommandTree(client)


def test_audit_rejects_ctx_args_kwargs_from_public_schema():
    tree = _tree()

    async def bad_callback(
        interaction: discord.Interaction,
        ctx: str,
        args: str = "",
        kwargs: str = "",
    ) -> None:
        return None

    tree.add_command(
        app_commands.Command(
            name="broken",
            description="Regression fixture",
            callback=bad_callback,
        )
    )

    with pytest.raises(RuntimeError) as exc:
        v105.audit_tree(tree)

    message = str(exc.value)
    assert "/broken" in message
    assert "ctx" in message
    assert "args" in message
    assert "kwargs" in message


def test_audit_accepts_normal_user_options():
    tree = _tree()

    async def clean_callback(
        interaction: discord.Interaction,
        member: str,
        reason: str = "",
    ) -> None:
        return None

    tree.add_command(
        app_commands.Command(
            name="clean",
            description="Regression fixture",
            callback=clean_callback,
        )
    )

    audited = v105.audit_tree(tree)
    assert "clean" in audited


def test_direct_root_bridge_removes_internal_context_from_ping():
    bot = commands.Bot(command_prefix="+", intents=discord.Intents.none(), help_command=None)

    @bot.command(name="ping")
    async def ping_prefix(ctx: commands.Context, target: str = "") -> None:
        return None

    async def stale_ping(
        interaction: discord.Interaction,
        ctx: str,
        args: str = "",
    ) -> None:
        return None

    bot.tree.add_command(
        app_commands.Command(name="ping", description="Old broken ping", callback=stale_ping)
    )
    assert {parameter.name for parameter in bot.tree.get_command("ping").parameters} >= {"ctx", "args"}

    assert v105._replace_direct_root(bot, "ping") is True
    rebuilt = bot.tree.get_command("ping")
    assert rebuilt is not None
    assert not (
        {parameter.name for parameter in rebuilt.parameters}
        & v105.FORBIDDEN_PUBLIC_PARAMETERS
    )
    assert {parameter.name for parameter in rebuilt.parameters} == {"target"}


@pytest.mark.asyncio
async def test_setup_v103_has_zero_user_options():
    bot = commands.Bot(command_prefix="+", intents=discord.Intents.none(), help_command=None)

    class SentriXSetup(commands.Cog):
        async def send_setup(self, interaction: discord.Interaction) -> None:
            return None

    await bot.add_cog(SentriXSetup())
    assert v103._replace_setup_slash(bot) is True

    setup = bot.tree.get_command("setup")
    assert setup is not None
    assert list(setup.parameters) == []
