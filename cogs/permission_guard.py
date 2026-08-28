"""Branchement des deux transports Discord sur la matrice d'accès unique.

Ce module ne DÉCIDE rien. Il se contente de :
- extraire le nom racine de la commande, identiquement pour ``+`` et ``/`` ;
- appeler ``utils.access_matrix.evaluate()`` ;
- rendre le refus lisible.

Toute règle d'accès vit dans ``utils/access_matrix.py``. Ne pas rajouter de
condition ici : ce serait recréer la divergence que cette refonte supprime.
"""
from __future__ import annotations

import inspect
import logging
from typing import Any

import discord
from discord.ext import commands

from utils import access_matrix
from utils.access_matrix import AccessDecision, evaluate, normalise
from utils.checks import BotPermissionError

logger = logging.getLogger("bot.permission-guard")

# Réexports de compatibilité : d'anciens modules importent ces noms.
PROOF_PUBLIC_COMMANDS = frozenset({"proof", "proofstatus"})
PROOF_ADMIN_COMMANDS = frozenset({
    "proofsetup", "proofexample", "proofexample-remove", "proofexamples",
    "proofpanel", "proofreset",
})


def command_root_name(command: Any) -> str:
    if command is None:
        return ""
    root = getattr(command, "root_parent", None) or command
    return normalise(getattr(root, "name", ""))


def interaction_root_name(interaction: discord.Interaction) -> str:
    command = getattr(interaction, "command", None)
    name = command_root_name(command)
    if name:
        return name
    data = getattr(interaction, "data", None)
    if isinstance(data, dict):
        return normalise(data.get("name"))
    return ""


async def evaluate_command_access(
    bot: commands.Bot, *, command_name: str, author: Any, guild: Any
) -> AccessDecision:
    """Point d'entrée unique. NE PAS envelopper : modifier la matrice."""
    return await evaluate(bot, command_name=command_name, author=author, guild=guild)


async def evaluate_interaction_access(
    bot: commands.Bot, interaction: discord.Interaction
) -> AccessDecision:
    return await evaluate(
        bot,
        command_name=interaction_root_name(interaction),
        author=getattr(interaction, "user", None),
        guild=getattr(interaction, "guild", None),
    )


async def _send_interaction_denial(
    interaction: discord.Interaction, decision: AccessDecision
) -> None:
    embed = discord.Embed(
        title="SentriX — Permission insuffisante",
        description=decision.message,
        colour=discord.Colour(0xED4245),
    )
    embed.set_footer(text="SentriX • Permissions identiques en + et /")
    kwargs = {
        "embed": embed,
        "ephemeral": True,
        "allowed_mentions": discord.AllowedMentions.none(),
    }
    try:
        if interaction.response.is_done():
            await interaction.followup.send(**kwargs)
        else:
            await interaction.response.send_message(**kwargs)
    except (discord.Forbidden, discord.HTTPException, discord.InteractionResponded):
        logger.debug("Impossible d'envoyer le refus slash.", exc_info=True)


def _force_help_public(bot: commands.Bot) -> None:
    command = bot.get_command("help")
    if command is None:
        return
    for holder in (command, getattr(command, "app_command", None)):
        if holder is None:
            continue
        checks_list = getattr(holder, "checks", None)
        if isinstance(checks_list, list) and checks_list:
            checks_list.clear()
        holder._sentrix_help_public = True


def _is_redundant_authorization_check(predicate: Any) -> bool:
    if getattr(predicate, "_sentrix_keep", False):
        return False

    label = str(getattr(predicate, "_sentrix_permission_label", "") or "")
    if label:
        # Keep the explicit global-owner check as a defence in depth. The matrix
        # returns the same decision, so it cannot create +// divergence.
        if "Propriétaire global SentriX" in label:
            return False
        return True

    module = str(getattr(predicate, "__module__", "") or "")
    qualname = str(getattr(predicate, "__qualname__", "") or "")
    if module.startswith("discord.ext.commands"):
        return (
            "has_permissions.<locals>.predicate" in qualname
            or "has_guild_permissions.<locals>.predicate" in qualname
        )
    return False


def _strip_redundant_local_checks(bot: commands.Bot) -> int:
    """Remove only local authorization checks replaced by the access matrix.

    Context and execution-safety checks (guild_only, target hierarchy,
    modifiability, bot permissions, business validation...) are deliberately
    preserved.
    """
    removed = 0
    for command in bot.walk_commands():
        root = command.root_parent or command
        if normalise(getattr(root, "name", "")) not in access_matrix.KNOWN_COMMANDS:
            continue
        for holder in (command, getattr(command, "app_command", None)):
            if holder is None:
                continue
            checks_list = getattr(holder, "checks", None)
            if not isinstance(checks_list, list):
                continue
            keep = [c for c in checks_list if not _is_redundant_authorization_check(c)]
            removed += len(checks_list) - len(keep)
            checks_list[:] = keep
    return removed


def install(bot: commands.Bot) -> None:
    _force_help_public(bot)
    if getattr(bot, "_sentrix_permission_guard_installed", False):
        return

    removed = _strip_redundant_local_checks(bot)

    async def prefix_permission_guard(ctx: commands.Context) -> bool:
        command = getattr(ctx, "command", None)
        if command is None:
            return True
        decision = await evaluate_command_access(
            bot,
            command_name=command_root_name(command),
            author=getattr(ctx, "author", None),
            guild=getattr(ctx, "guild", None),
        )
        if decision.allowed:
            return True
        raise BotPermissionError(decision.message)

    prefix_permission_guard._sentrix_permission_guard = True
    bot.global_permission_check = prefix_permission_guard

    original_tree_check = bot.tree.interaction_check

    async def slash_permission_guard(interaction: discord.Interaction) -> bool:
        previous = original_tree_check(interaction)
        if inspect.isawaitable(previous):
            previous = await previous
        if previous is False:
            return False
        if interaction.type != discord.InteractionType.application_command:
            return True
        decision = await evaluate_interaction_access(bot, interaction)
        if decision.allowed:
            return True
        logger.warning(
            "Slash refusé command=%s user=%s guild=%s policy=%s",
            interaction_root_name(interaction),
            getattr(getattr(interaction, "user", None), "id", None),
            getattr(interaction, "guild_id", None),
            decision.policy,
        )
        await _send_interaction_denial(interaction, decision)
        return False

    slash_permission_guard._sentrix_permission_guard = True
    slash_permission_guard._sentrix_previous_tree_check = original_tree_check
    bot.tree.interaction_check = slash_permission_guard
    bot._sentrix_permission_guard_installed = True
    logger.info(
        "Permissions SentriX : matrice unique active (%s commandes classées, "
        "%s check(s) local(aux) redondant(s) retiré(s)).",
        len(access_matrix.KNOWN_COMMANDS),
        removed,
    )


__all__ = [
    "AccessDecision", "evaluate_command_access", "evaluate_interaction_access",
    "command_root_name", "interaction_root_name", "install",
]
