from __future__ import annotations

import asyncio

from discord.ext import commands

from ..bot_mastery_runtime import install as install_mastery
from ..bot_resilience_v11 import setup as install_resilience
from ..bot_v12_machine import setup as install_v12_machine
from ..bot_v12_ticket_sla import setup as install_v12_ticket_sla
from ..command_catalog_cleanup import install as install_catalog
from ..custom_command_failsafe_v11 import setup as install_custom_command_failsafe
from ..operations_center import install as install_operations
from ..production_readiness_runtime import install as install_readiness

_ready_task = None


async def _after_ready(bot: commands.Bot):
    await bot.wait_until_ready()
    await asyncio.sleep(1)
    await install_mastery(bot, "ready")
    await install_readiness(bot, "ready")


async def install(bot: commands.Bot):
    install_catalog(bot)
    await install_operations(bot)
    await install_mastery(bot, "cogs.ai")
    await install_readiness(bot, "cogs.ai")
    await install_resilience(bot)
    await install_custom_command_failsafe(bot)
    await install_v12_machine(bot)
    await install_v12_ticket_sla(bot)

    global _ready_task
    started = bool(getattr(getattr(bot, "http", None), "token", None))
    if started and (_ready_task is None or _ready_task.done()):
        _ready_task = asyncio.create_task(_after_ready(bot))

    command = bot.get_command("code")
    if command is not None:
        command.hidden = False
