"""Extension Railway finale : impose le rendu texte natif après tous les anciens runtimes."""
from discord.ext import commands

from .plain_text_all_runtime import install


async def setup(bot: commands.Bot) -> None:
    # Installation immédiate, puis réinstallation au on_ready. Le loader historique de
    # SentriX applique encore quelques finalizers APRES setup(); on_ready garantit donc
    # que notre politique texte redevient réellement la dernière couche active.
    install(bot)

    if getattr(bot, "_sentrix_plain_text_ready_listener", False):
        return

    async def apply_plain_text_when_ready():
        install(bot)

    bot.add_listener(apply_plain_text_when_ready, "on_ready")
    bot._sentrix_plain_text_ready_listener = True
