import asyncio
import importlib.util
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "cogs" / "no_cooldown_final.py"
GUARD_PATH = ROOT / "cogs" / "slash_error_completion_guard.py"

SPEC = importlib.util.spec_from_file_location("sentrix_no_cooldown_final", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
no_cooldown = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(no_cooldown)


async def prefix_callback(ctx):
    return None


async def slash_callback(interaction: discord.Interaction):
    return None


async def permission_check(interaction: discord.Interaction) -> bool:
    return True


def limited_prefix(name: str) -> commands.Command:
    command = commands.Command(prefix_callback, name=name)
    command._buckets = commands.CooldownMapping.from_cooldown(
        1, 60.0, commands.BucketType.user
    )
    command._max_concurrency = commands.MaxConcurrency(
        1, per=commands.BucketType.user, wait=False
    )
    return command


def limited_slash(name: str):
    decorator = app_commands.checks.cooldown(1, 60.0)
    command = app_commands.Command(name=name, description="probe", callback=slash_callback)
    decorator(command)
    command.add_check(permission_check)
    return command


async def run_test():
    bot = commands.Bot(command_prefix="+", intents=discord.Intents.none())

    async def old_global(ctx):
        return True

    async def isolated_global(ctx):
        return True

    isolated_global._sentrix_cooldown_isolated = True
    bot.global_cooldown_check = old_global
    bot._sentrix_isolated_global_cooldown_check = isolated_global
    bot.add_check(old_global)
    bot.add_check(isolated_global)

    existing = limited_prefix("existing")
    bot.add_command(existing)

    slash = limited_slash("slashprobe")
    bot.tree.add_command(slash)
    assert any(no_cooldown._is_app_cooldown_check(check) for check in slash.checks)
    assert permission_check in slash.checks

    no_cooldown.install(bot)

    # Les deux anciens checks globaux ont disparu.
    assert old_global not in bot._checks
    assert isolated_global not in bot._checks

    # Une commande existante n'a plus ni recharge ni verrou de concurrence.
    assert existing._buckets.valid is False
    assert existing._max_concurrency is None
    for _ in range(20):
        existing._prepare_cooldowns(None)

    # Une commande ajoutée APRES l'installation est également nettoyée.
    future = limited_prefix("future")
    bot.add_command(future)
    assert future._buckets.valid is False
    assert future._max_concurrency is None

    # Le cooldown slash est retiré, mais le check de permission ordinaire reste intact.
    assert not any(no_cooldown._is_app_cooldown_check(check) for check in slash.checks)
    assert permission_check in slash.checks

    # Même une vraie commande slash créée ensuite est nettoyée juste avant ses checks.
    later_slash = limited_slash("laterslash")
    assert any(no_cooldown._is_app_cooldown_check(check) for check in later_slash.checks)
    assert await later_slash._check_can_run(object()) is True
    assert not any(no_cooldown._is_app_cooldown_check(check) for check in later_slash.checks)
    assert permission_check in later_slash.checks

    state = bot.no_cooldown_final_state
    assert state["installed"] is True
    await bot.close()


def static_contracts():
    source = MODULE_PATH.read_text(encoding="utf-8")
    guard = GUARD_PATH.read_text(encoding="utf-8")
    compile(source, str(MODULE_PATH), "exec")
    compile(guard, str(GUARD_PATH), "exec")

    assert "command._max_concurrency = None" in source
    assert "CooldownMapping(None, commands.BucketType.default)" in source
    assert "commands.Command._prepare_cooldowns = prepare_no_cooldowns" in source
    assert "_create_cooldown_decorator.<locals>.predicate" in source
    assert "no_cooldown_final.install(bot)" in guard
    assert "cooldown_isolation_fix.install(bot)" not in guard
    assert guard.index("await logs_unified_v6.install(bot)") < guard.index("no_cooldown_final.install(bot)")


if __name__ == "__main__":
    static_contracts()
    asyncio.run(run_test())
    print("no cooldown final runtime: ok")
