import asyncio
from types import SimpleNamespace

import discord
from discord.ext import commands

from cogs import cooldown_isolation_fix


class FakeDB:
    async def is_bot_creator(self, user_id: int) -> bool:
        return False


class TestBot(commands.Bot):
    async def global_cooldown_check(self, ctx):
        return True


class FakeContext:
    def __init__(self, command_name: str, user_id: int = 42424242):
        self.author = SimpleNamespace(id=user_id)
        self.command = SimpleNamespace(
            qualified_name=command_name,
            name=command_name,
        )
        self.interaction = None
        self.message = SimpleNamespace(author=self.author)


async def run_test():
    bot = TestBot(command_prefix="+", intents=discord.Intents.none())
    bot.db = FakeDB()

    legacy = bot.global_cooldown_check
    bot.add_check(legacy)
    assert legacy in bot._checks

    cooldown_isolation_fix.install(bot)
    check = bot._sentrix_isolated_global_cooldown_check

    # Le vieux check partagé doit avoir disparu et le nouveau doit être actif.
    assert legacy not in bot._checks
    assert check in bot._checks

    # Trois +ping passent avec la config actuelle (3 / 5 s).
    for _ in range(3):
        assert await check(FakeContext("ping")) is True

    # Le quatrième +ping est bien refroidi.
    try:
        await check(FakeContext("ping"))
    except commands.CommandOnCooldown:
        pass
    else:
        raise AssertionError("Le quatrième +ping aurait dû être en cooldown")

    # Mais +help est une autre commande : son quota est totalement indépendant.
    assert await check(FakeContext("help")) is True

    mappings = bot.cooldown_isolation_state["mappings"]
    assert set(mappings) == {"ping", "help"}

    await bot.close()


if __name__ == "__main__":
    asyncio.run(run_test())
    print("cooldown isolation runtime: ok")
