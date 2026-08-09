"""Protection stricte de +wipe-server.

Seul le propriétaire réel du serveur Discord peut utiliser la commande destructrice
+wipe-server. Les administrateurs, gestionnaires du bot, cofondateurs et même le
propriétaire global de SentriX ne contournent pas cette règle sur un serveur qui ne leur
appartient pas.

+create-server n'est volontairement pas modifié : il conserve ses permissions actuelles.
"""
from __future__ import annotations

import logging

from discord.ext import commands

from utils import checks

logger = logging.getLogger("bot.wipe-owner-only")


async def _guild_owner_only(ctx: commands.Context) -> bool:
    if ctx.guild is None:
        raise checks.BotPermissionError("Cette commande doit être utilisée dans un serveur.")
    if ctx.author.id == ctx.guild.owner_id:
        return True
    raise checks.BotPermissionError(
        "Seul le **propriétaire du serveur Discord** peut utiliser `+wipe-server`. "
        "Même un administrateur ou un gestionnaire du bot ne peut pas lancer cette commande."
    )


def install(bot: commands.Bot) -> None:
    """Ajoute un second verrou fail-closed sur la commande wipe déjà enregistrée."""
    command = bot.get_command("wipe-server") or bot.get_command("wipe-serveur")
    if command is None:
        return
    if getattr(command, "_sentrix_guild_owner_only", False):
        return

    command.add_check(_guild_owner_only)
    command._sentrix_guild_owner_only = True
    logger.info("+wipe-server verrouillé au propriétaire réel du serveur Discord.")
