"""Politique de permissions canonique de SentriX.

Une seule matrice est utilisée pour les commandes + et /. Elle est fail-closed et sépare
clairement : public, propriétaire, modération quotidienne, permissions Discord sensibles
et catégories de gestion. Le rôle de modération configuré ne remplace jamais une
permission structurelle telle que Gérer les rôles/salons/expressions.
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

logger = logging.getLogger("bot.permission-policy")

SAFE_MOD_ROLE_PERMISSIONS = frozenset({
    "ban_members",
    "kick_members",
    "moderate_members",
    "manage_messages",
    "manage_nicknames",
    "move_members",
})


@dataclass(frozen=True, slots=True)
class AccessDecision:
    allowed: bool
    reason: str = ""
    policy: str = ""


def _policy_module(bot: commands.Bot):
    return sys.modules.get(bot.__class__.__module__) or sys.modules.get("main") or sys.modules.get("__main__")


def _policy_sets(bot: commands.Bot):
    module = _policy_module(bot)
    if module is None:
        return frozenset(), frozenset(), frozenset(), {}, {}
    return (
        frozenset(getattr(module, "PUBLIC_COMMANDS", frozenset())),
        frozenset(getattr(module, "OWNER_ONLY_COMMANDS", frozenset())),
        frozenset(getattr(module, "CUSTOM_PERMISSION_COMMANDS", frozenset())),
        dict(getattr(module, "DISCORD_PERMISSION_COMMANDS", {}) or {}),
        dict(getattr(module, "CATEGORY_COMMANDS", {}) or {}),
    )


def _normalise(value: Any) -> str:
    return str(value or "").strip().casefold()


def command_root_name(command: Any) -> str:
    if command is None:
        return ""
    root = getattr(command, "root_parent", None) or command
    return _normalise(getattr(root, "name", ""))


def interaction_root_name(interaction: discord.Interaction) -> str:
    name = command_root_name(getattr(interaction, "command", None))
    if name:
        return name
    data = getattr(interaction, "data", None)
    return _normalise(data.get("name")) if isinstance(data, dict) else ""


async def _is_verified_owner(bot: commands.Bot, user_id: int) -> bool:
    user_id = int(user_id)
    if user_id == PRIMARY_CREATOR_ID or user_id in config.OWNER_IDS:
        return True
    try:
        return bool(await bot.db.is_bot_creator(user_id))
    except Exception:
        logger.exception("Vérification propriétaire impossible pour user=%s ; refus par sécurité.", user_id)
        return False


def _permissions(author: Any):
    return getattr(author, "guild_permissions", None)


async def _is_manager_for(bot: commands.Bot, guild: Any, author: Any, category: str) -> bool:
    if guild is None or author is None:
        return False
    perms = _permissions(author)
    if perms is not None and bool(getattr(perms, "administrator", False)):
        return True
    guild_id, user_id = getattr(guild, "id", None), getattr(author, "id", None)
    if guild_id is None or user_id is None:
        return False
    try:
        if not await bot.db.is_bot_manager(int(guild_id), int(user_id)):
            return False
        return bool(await bot.db.has_manager_permission(int(guild_id), int(user_id), category))
    except Exception:
        logger.exception("Vérification gestionnaire impossible guild=%s user=%s category=%s.", guild_id, user_id, category)
        return False


async def _has_discord_or_modrole_permission(bot: commands.Bot, guild: Any, author: Any, permission: str) -> bool:
    if guild is None or author is None:
        return False
    perms = _permissions(author)
    if perms is not None and bool(getattr(perms, permission, False)):
        return True

    # Important : le rôle « modérateur SentriX » ne donne un raccourci que pour les
    # actions quotidiennes. Jamais pour gérer rôles, salons, webhooks ou expressions.
    if permission not in SAFE_MOD_ROLE_PERMISSIONS:
        return False

    guild_id = getattr(guild, "id", None)
    if guild_id is None:
        return False
    try:
        conf = await bot.db.get_guild_config(int(guild_id))
    except Exception:
        logger.exception("Lecture du rôle de modération impossible guild=%s.", guild_id)
        return False
    mod_role_id = conf["mod_role"] if conf and conf["mod_role"] else None
    if not mod_role_id:
        return False
    try:
        wanted = int(mod_role_id)
        return any(int(getattr(role, "id", 0)) == wanted for role in getattr(author, "roles", ()))
    except (TypeError, ValueError):
        return False


async def _can_use_embed_builder(bot: commands.Bot, guild: Any, author: Any) -> bool:
    if guild is None or author is None:
        return False
    perms = _permissions(author)
    if perms is not None and (
        bool(getattr(perms, "manage_messages", False))
        or bool(getattr(perms, "manage_guild", False))
        or bool(getattr(perms, "administrator", False))
    ):
        return True
    guild_id, user_id = getattr(guild, "id", None), getattr(author, "id", None)
    if guild_id is None or user_id is None:
        return False
    try:
        if await bot.db.is_bot_manager(int(guild_id), int(user_id)):
            if await bot.db.has_manager_permission(int(guild_id), int(user_id), "embeds"):
                return True
        rows = await bot.db.fetchall(
            "SELECT role_id FROM embed_allowed_roles WHERE guild_id = ?",
            (int(guild_id),),
        )
    except Exception:
        logger.exception("Vérification permission embeds impossible guild=%s user=%s.", guild_id, user_id)
        return False
    allowed = {int(row["role_id"]) for row in rows}
    return any(int(getattr(role, "id", 0)) in allowed for role in getattr(author, "roles", ()))


async def evaluate_command_access(bot: commands.Bot, *, command_name: str, author: Any, guild: Any) -> AccessDecision:
    name = _normalise(command_name)
    if not name:
        return AccessDecision(False, "Commande impossible à identifier.", "invalid")

    public, owner_only, custom, discord_permissions, categories = _policy_sets(bot)
    if name in public:
        return AccessDecision(True, policy="public")

    user_id = getattr(author, "id", None)
    owner = bool(user_id is not None and await _is_verified_owner(bot, int(user_id)))
    if name in owner_only:
        return AccessDecision(True, policy="owner") if owner else AccessDecision(
            False, "Cette commande est réservée au propriétaire vérifié de SentriX.", "owner"
        )
    if owner:
        return AccessDecision(True, policy="owner-bypass")

    if name in custom:
        if await _can_use_embed_builder(bot, guild, author):
            return AccessDecision(True, policy="custom")
        return AccessDecision(False, "Cette commande est réservée au staff autorisé à créer des embeds.", "custom")

    required = discord_permissions.get(name)
    if required is not None:
        if await _has_discord_or_modrole_permission(bot, guild, author, required):
            return AccessDecision(True, policy=f"discord:{required}")
        if required in SAFE_MOD_ROLE_PERMISSIONS:
            reason = f"Permission requise : `{required}` ou rôle de modération configuré."
        else:
            reason = f"Permission Discord requise : `{required}`. Le rôle modérateur SentriX ne suffit pas pour cette action sensible."
        return AccessDecision(False, reason, f"discord:{required}")

    for category, names in categories.items():
        if name not in names:
            continue
        if await _is_manager_for(bot, guild, author, category):
            return AccessDecision(True, policy=f"manager:{category}")
        return AccessDecision(
            False,
            f"Cette commande de gestion exige Administrateur ou l'autorisation SentriX `{category}`.",
            f"manager:{category}",
        )

    if await _is_manager_for(bot, guild, author, "complete"):
        return AccessDecision(True, policy="fail-closed-admin")
    return AccessDecision(
        False,
        "Cette commande n'a pas encore de niveau d'accès validé et reste administrateur par sécurité.",
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
        logger.exception("Vérification propriétaire impossible pour un utilisateur blacklisté=%s.", user_id)
    return str(reason or "Aucune raison fournie")


async def evaluate_interaction_access(bot: commands.Bot, interaction: discord.Interaction) -> AccessDecision:
    reason = await _interaction_blacklist_reason(bot, getattr(interaction, "user", None))
    if reason is not None:
        return AccessDecision(False, f"Tu n'es pas autorisé à utiliser SentriX. Raison : {reason}", "global-blacklist")
    return await evaluate_command_access(
        bot,
        command_name=interaction_root_name(interaction),
        author=getattr(interaction, "user", None),
        guild=getattr(interaction, "guild", None),
    )


async def _send_interaction_denial(interaction: discord.Interaction, decision: AccessDecision) -> None:
    # Remplacé par final_interaction_policy pour obtenir exactement le même style + et /.
    text = decision.reason or "Tu n'as pas accès à cette commande."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
    except (discord.Forbidden, discord.HTTPException, discord.InteractionResponded):
        logger.debug("Refus slash impossible à envoyer.", exc_info=True)


def _force_help_public(bot: commands.Bot) -> None:
    command = bot.get_command("help")
    if command is None:
        return
    checks_list = getattr(command, "checks", None)
    if isinstance(checks_list, list):
        checks_list.clear()
    app = getattr(command, "app_command", None)
    app_checks = getattr(app, "checks", None)
    if isinstance(app_checks, list):
        app_checks.clear()
    command._sentrix_help_public = True


def install(bot: commands.Bot) -> None:
    _force_help_public(bot)
    if getattr(bot, "_sentrix_permission_guard_installed", False):
        return

    async def prefix_guard(ctx: commands.Context) -> bool:
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

    prefix_guard._sentrix_permission_guard = True
    bot.global_permission_check = prefix_guard

    previous_tree_check = bot.tree.interaction_check

    async def slash_guard(interaction: discord.Interaction) -> bool:
        previous = previous_tree_check(interaction)
        if inspect.isawaitable(previous):
            previous = await previous
        if previous is False or interaction.type != discord.InteractionType.application_command:
            return previous is not False
        decision = await evaluate_interaction_access(bot, interaction)
        if decision.allowed:
            return True
        try:
            from .command_hardening_v41 import release_slash
            release_slash(interaction)
        except Exception:
            pass
        logger.warning(
            "Slash refusée command=%s user=%s guild=%s policy=%s",
            interaction_root_name(interaction),
            getattr(getattr(interaction, "user", None), "id", None),
            getattr(interaction, "guild_id", None),
            decision.policy,
        )
        await _send_interaction_denial(interaction, decision)
        return False

    slash_guard._sentrix_permission_guard = True
    slash_guard._sentrix_previous_tree_check = previous_tree_check
    bot.tree.interaction_check = slash_guard
    bot._sentrix_permission_guard_installed = True
    bot._sentrix_permission_policy_owner = "cogs.permission_guard"
    logger.info("Matrice de permissions canonique active pour + et / (fail-closed).")


__all__ = [
    "SAFE_MOD_ROLE_PERMISSIONS", "AccessDecision", "command_root_name",
    "interaction_root_name", "evaluate_command_access", "evaluate_interaction_access", "install",
]
