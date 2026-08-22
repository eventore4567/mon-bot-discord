"""Extension Railway finale : installe le rendu texte natif après tous les anciens runtimes."""
from discord.ext import commands

from .plain_text_all_runtime import install


async def setup(bot: commands.Bot) -> None:
    install(bot)
