"""Politique de modération de contenu SentriX.

Règles globales demandées :
- seul le propriétaire réel du serveur Discord peut ajouter/retirer des whitelists ;
- le propriétaire du serveur est immunisé contre les filtres de contenu, et les
  filtres suivent l'escalade unique (un avertissement, puis le mute).

22/11/2026 : ces deux règles vivaient ici sous forme de remplacements des
méthodes d'AutoMod (_delete_and_warn, _delete_and_timeout, _maybe_escalate).
Elles sont désormais écrites dans cogs/automod.py lui-même ; ce module ne
garde que le verrouillage des whitelists.
- l'anti-nuke reste indépendant et conserve ses sanctions fortes en cas d'attaque.

"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import checks

logger = logging.getLogger("bot.content-filter-policy")

# Toute opération qui crée ou retire une exemption de sécurité est propriétaire-only.
_OWNER_ONLY_WHITELIST_COMMANDS = {
    "whitelist-domain",
    "unwhitelist-domain",
    "antinuke-whitelist-add",
    "antinuke-whitelist-remove",
    "automod-exempt-role-add",
    "automod-exempt-role-remove",
}



async def _guild_owner_only(ctx: commands.Context) -> bool:
    if ctx.guild is None:
        raise checks.BotPermissionError("Cette commande doit être utilisée dans un serveur.")
    if ctx.author.id == ctx.guild.owner_id:
        return True
    raise checks.BotPermissionError(
        "Seul le **propriétaire du serveur Discord** peut modifier une whitelist ou une exemption de sécurité."
    )


async def _guild_owner_only_interaction(interaction: discord.Interaction) -> bool:
    guild = interaction.guild
    if guild is not None and interaction.user.id == guild.owner_id:
        return True
    raise app_commands.CheckFailure(
        "Seul le propriétaire du serveur Discord peut modifier une whitelist ou une exemption de sécurité."
    )


def _install_owner_only_whitelist_guards(bot: commands.Bot) -> None:
    for name in _OWNER_ONLY_WHITELIST_COMMANDS:
        command = bot.get_command(name)
        if command is None or getattr(command, "_sentrix_owner_only_whitelist", False):
            continue

        command.add_check(_guild_owner_only)
        app_command = getattr(command, "app_command", None)
        if app_command is not None and hasattr(app_command, "add_check"):
            app_command.add_check(_guild_owner_only_interaction)

        command._sentrix_owner_only_whitelist = True
        logger.info("Whitelist verrouillée au propriétaire du serveur : %s", name)


def install(bot: commands.Bot) -> None:
    """Idempotent et rappelable après chaque chargement d'extension."""
    _install_owner_only_whitelist_guards(bot)
