from __future__ import annotations

import discord
from discord.ext import commands

from cogs.command_final_guard_v76 import _needs_repair, install


def _bot() -> commands.Bot:
    return commands.Bot(command_prefix="+", intents=discord.Intents.none())


def test_v76_repairs_generic_wrapper_before_users_see_internal_arguments():
    bot = _bot()

    @bot.command(name="demo")
    async def demo(ctx: commands.Context):
        return None

    command = bot.get_command("demo")
    original = command.callback

    async def contaminated(*args, **kwargs):
        return await original(*args, **kwargs)

    contaminated._sentrix_original = original
    command.callback = contaminated
    assert _needs_repair(command), list(command.clean_params)

    install(bot)

    assert not _needs_repair(command), list(command.clean_params)
    assert getattr(getattr(bot.invoke, "__func__", bot.invoke), "_sentrix_command_final_guard_v76", False)


def test_v76_replaces_verification_commands_with_no_argument_setup():
    bot = _bot()

    @bot.command(name="verify-panel")
    async def verify_panel(ctx: commands.Context):
        return None

    @bot.command(name="verify-setup")
    async def old_verify_setup(ctx: commands.Context, role: str):
        return role

    install(bot)

    assert bot.get_command("verify-panel") is None
    setup_command = bot.get_command("verify-setup")
    assert setup_command is not None
    assert list(setup_command.clean_params) == []
    assert not _needs_repair(setup_command)
