"""Matrice centrale de permissions SentriX pour commandes + et /.

Règles :
- commandes publiques : membres ;
- modération : permission Discord exacte ;
- gestion/configuration : Administrateur ;
- owner-only : propriétaire global SentriX ;
- aucun ancien gestionnaire du bot de serveur ne peut s'auto-accorder ces droits.
"""
from __future__ import annotations

import inspect
import logging
import sys
from dataclasses import dataclass
from typing import Any

import discord
from discord.ext import commands

import config
from database.db import PRIMARY_CREATOR_ID
from utils.checks import BotPermissionError
from utils.command_permissions import permission_label

logger = logging.getLogger("bot.permission-guard")

# Le module de preuve est chargé dynamiquement après les extensions historiques. Sa
# politique reste néanmoins centralisée ici afin que les commandes préfixées et slash
# reçoivent exactement le même niveau d'accès.
PROOF_PUBLIC_COMMANDS = frozenset({"proof", "proofstatus"})
PROOF_ADMIN_COMMANDS = frozenset({
    "proofsetup", "proofexample", "proofexample-remove", "proofexamples", "proofpanel", "proofreset",
})


@dataclass(frozen=True, slots=True)
class AccessDecision:
    allowed: bool
    reason: str = ""
    policy: str = ""


def _policy_module(bot: commands.Bot):
    return sys.modules.get(bot.__class__.__module__)


def _policy_sets(bot: commands.Bot):
    module = _policy_module(bot)
    if module is None:
        return frozenset(), frozenset(), frozenset(), {}, {}
    return (
        frozenset(getattr(module, "PUBLIC_COMMANDS", frozenset())),
        frozenset(getattr(module, "OWNER_ONLY_COMMANDS", frozenset())),
        frozenset(getattr(module, "CUSTOM_PERMISSION_COMMANDS", frozenset())),
        dict(getattr(module, "DISCORD_PERMISSION_COMMANDS", {})),
        dict(getattr(module, "CATEGORY_COMMANDS", {})),
    )


def _normalise_name(value: Any) -> str:
    return str(value or "").strip().casefold()


def command_root_name(command: Any) -> str:
    if command is None:
        return ""
    root = getattr(command, "root_parent", None) or command
    return _normalise_name(getattr(root, "name", ""))


def interaction_root_name(interaction: discord.Interaction) -> str:
    command = getattr(interaction, "command", None)
    name = command_root_name(command)
    if name:
        return name
    data = getattr(interaction, "data", None)
    if isinstance(data, dict):
        return _normalise_name(data.get("name"))
    return ""


async def _is_verified_owner(bot: commands.Bot, user_id: int) -> bool:
    user_id = int(user_id)
    if user_id == PRIMARY_CREATOR_ID or user_id in config.OWNER_IDS:
        return True
    try:
        return bool(await bot.db.is_bot_creator(user_id))
    except Exception:
        logger.exception("Vérification propriétaire impossible pour user=%s", user_id)
        return False


def _member_permissions(author: Any):
    return getattr(author, "guild_permissions", None)


def _is_administrator(author: Any) -> bool:
    permissions = _member_permissions(author)
    return bool(permissions is not None and getattr(permissions, "administrator", False))


def _has_discord_permission(author: Any, permission: str) -> bool:
    permissions = _member_permissions(author)
    return bool(permissions is not None and getattr(permissions, permission, False))


async def _can_use_embed_builder(bot: commands.Bot, guild: Any, author: Any) -> bool:
    if guild is None or author is None:
        return False
    permissions = _member_permissions(author)
    if permissions is not None and (
        bool(getattr(permissions, "manage_messages", False))
        or bool(getattr(permissions, "manage_guild", False))
    ):
        return True

    guild_id = getattr(guild, "id", None)
    if guild_id is None:
        return False
    try:
        rows = await bot.db.fetchall(
            "SELECT role_id FROM embed_allowed_roles WHERE guild_id = ?",
            (int(guild_id),),
        )
    except Exception:
        logger.exception("Vérification rôles +embed impossible pour guild=%s", guild_id)
        return False

    allowed_role_ids = {int(row["role_id"]) for row in rows}
    return any(int(getattr(role, "id", 0)) in allowed_role_ids for role in getattr(author, "roles", ()))


async def evaluate_command_access(bot: commands.Bot, *, command_name: str, author: Any, guild: Any) -> AccessDecision:
    name = _normalise_name(command_name)
    if not name:
        return AccessDecision(False, "Commande impossible à identifier.", "invalid")

    public, owner_only, custom, discord_permissions, categories = _policy_sets(bot)

    if name in public or name in PROOF_PUBLIC_COMMANDS:
        return AccessDecision(True, policy="public")

    user_id = getattr(author, "id", None)
    owner = bool(user_id is not None and await _is_verified_owner(bot, int(user_id)))

    if name in owner_only:
        if owner:
            return AccessDecision(True, policy="owner")
        return AccessDecision(False, "Cette commande est réservée au **propriétaire global de SentriX**.", "owner")

    if owner:
        return AccessDecision(True, policy="owner-bypass")

    if name in PROOF_ADMIN_COMMANDS:
        if _is_administrator(author):
            return AccessDecision(True, policy="admin:proof")
        return AccessDecision(
            False,
            "Vous ne pouvez pas utiliser cette commande.\n\n**Permission requise :** Administrateur",
            "admin:proof",
        )

    if name in custom:
        if await _can_use_embed_builder(bot, guild, author):
            return AccessDecision(True, policy="custom")
        return AccessDecision(
            False,
            "Vous ne pouvez pas utiliser cette commande.\n\n"
            "**Permission requise :** Gérer les messages / Gérer le serveur / rôle +embed autorisé",
            "custom",
        )

    required_permission = discord_permissions.get(name)
    if required_permission is not None:
        if _has_discord_permission(author, required_permission):
            return AccessDecision(True, policy=f"discord:{required_permission}")
        return AccessDecision(
            False,
            "Vous ne pouvez pas utiliser cette commande.\n\n"
            f"**Permission requise :** {permission_label(required_permission)}",
            f"discord:{required_permission}",
        )

    for category, names in categories.items():
        if name not in names:
            continue
        if _is_administrator(author):
            return AccessDecision(True, policy=f"admin:{category}")
        return AccessDecision(
            False,
            "Vous ne pouvez pas utiliser cette commande.\n\n**Permission requise :** Administrateur",
            f"admin:{category}",
        )

    if _is_administrator(author):
        return AccessDecision(True, policy="fail-closed-admin")
    return AccessDecision(
        False,
        "Cette commande n'a pas encore de niveau d'accès public validé.\n\n"
        "**Permission requise :** Administrateur",
        "fail-closed",
    )


async def _interaction_blacklist_reason(bot: commands.Bot, author: Any) -> str | None:
    user_id = getattr(author, "id", None)
    if user_id is None:
        return None
    user_id = int(user_id)
    cache = getattr(bot, "blacklist_cache", {})
    reason = cache.get(user_id) if isinstance(cache, dict) else None
    if reason is None:
        return None
    if user_id == PRIMARY_CREATOR_ID or user_id in config.OWNER_IDS:
        return None
    try:
        if await bot.db.is_bot_creator(user_id):
            return None
    except Exception:
        logger.exception("Vérification propriétaire impossible pour user blacklist=%s", user_id)
    return str(reason or "Aucune raison fournie")


async def evaluate_interaction_access(bot: commands.Bot, interaction: discord.Interaction) -> AccessDecision:
    reason = await _interaction_blacklist_reason(bot, getattr(interaction, "user", None))
    if reason is not None:
        return AccessDecision(
            False,
            f"Vous n'êtes pas autorisé à utiliser SentriX. Raison : {reason}",
            "global-blacklist",
        )
    return await evaluate_command_access(
        bot,
        command_name=interaction_root_name(interaction),
        author=getattr(interaction, "user", None),
        guild=getattr(interaction, "guild", None),
    )


async def _send_interaction_denial(interaction: discord.Interaction, decision: AccessDecision) -> None:
    embed = discord.Embed(
        title="SentriX — Permission insuffisante",
        description=decision.reason or "Vous ne pouvez pas utiliser cette commande.",
        colour=discord.Colour(0xED4245),
    )
    embed.set_footer(text="SentriX • Permissions")
    kwargs = {"embed": embed, "ephemeral": True, "allowed_mentions": discord.AllowedMentions.none()}
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
    checks_list = getattr(command, "checks", None)
    if isinstance(checks_list, list) and checks_list:
        checks_list.clear()
    app_command = getattr(command, "app_command", None)
    app_checks = getattr(app_command, "checks", None) if app_command is not None else None
    if isinstance(app_checks, list) and app_checks:
        app_checks.clear()
    command._sentrix_help_public = True
    if app_command is not None:
        app_command._sentrix_help_public = True


def install(bot: commands.Bot) -> None:
    _force_help_public(bot)
    if getattr(bot, "_sentrix_permission_guard_installed", False):
        return

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
        raise BotPermissionError(decision.reason)

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
            "Commande slash refusée (command=%s user=%s guild=%s policy=%s)",
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

    logger.info("Permissions SentriX : matrice unique +/slash, staff par permission Discord, gestion admin, owner global.")