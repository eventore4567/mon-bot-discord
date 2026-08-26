"""Politique d'accès finale pour commandes préfixées ET slash.

Le préfixe possède déjà un contrôle fail-closed dans main.py. Cette couche applique la
même politique au CommandTree Discord, force +help public, et empêche les commandes
propriétaire/administration de consommer le catalogue slash.
"""
from __future__ import annotations

import logging
from types import MethodType

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("bot.command-access-v2")


async def _is_bot_owner(bot: commands.Bot, user_id: int) -> bool:
    import config
    from database.db import PRIMARY_CREATOR_ID

    if user_id == PRIMARY_CREATOR_ID or user_id in config.OWNER_IDS:
        return True
    try:
        return bool(await bot.db.is_bot_creator(user_id))
    except Exception:
        return False


async def _has_mod_or_permission(bot: commands.Bot, interaction: discord.Interaction, permission: str) -> bool:
    member = interaction.user
    guild = interaction.guild
    if guild is None or not isinstance(member, discord.Member):
        return False
    if getattr(member.guild_permissions, permission, False):
        return True
    try:
        conf = await bot.db.get_guild_config(guild.id)
    except Exception:
        conf = None
    if conf and conf["mod_role"]:
        role = guild.get_role(conf["mod_role"])
        if role and role in member.roles:
            return True
    return False


async def _has_manager_access(bot: commands.Bot, interaction: discord.Interaction, category: str) -> bool:
    member = interaction.user
    guild = interaction.guild
    if await _is_bot_owner(bot, member.id):
        return True
    if guild is None or not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.administrator:
        return True
    try:
        if not await bot.db.is_bot_manager(guild.id, member.id):
            return False
        return bool(await bot.db.has_manager_permission(guild.id, member.id, category))
    except Exception:
        return False


def _canonical_root(interaction: discord.Interaction) -> str:
    data = interaction.data if isinstance(interaction.data, dict) else {}
    name = str(data.get("name") or "").casefold()
    if name == "nick":
        return "nickname"
    return name


async def _enforce(bot: commands.Bot, interaction: discord.Interaction) -> bool:
    import main

    if interaction.type != discord.InteractionType.application_command:
        return True

    name = _canonical_root(interaction)
    if not name:
        return True

    user_id = interaction.user.id
    owner = await _is_bot_owner(bot, user_id)

    if not owner and user_id in getattr(bot, "blacklist_cache", {}):
        raise app_commands.CheckFailure("Vous êtes sur la liste noire globale de SentriX.")

    if name in main.PUBLIC_COMMANDS:
        return True

    if name in main.OWNER_ONLY_COMMANDS:
        if owner:
            return True
        raise app_commands.CheckFailure("Commande réservée au propriétaire vérifié du bot.")

    required_permission = main.DISCORD_PERMISSION_COMMANDS.get(name)
    if required_permission is not None:
        if owner or await _has_mod_or_permission(bot, interaction, required_permission):
            return True
        raise app_commands.CheckFailure(
            f"Permission requise : {required_permission} ou rôle de modération configuré."
        )

    if name in main.CUSTOM_PERMISSION_COMMANDS:
        member = interaction.user
        if owner:
            return True
        if isinstance(member, discord.Member):
            perms = member.guild_permissions
            if perms.manage_messages or perms.manage_guild:
                return True
        if await _has_manager_access(bot, interaction, "embeds"):
            return True
        raise app_commands.CheckFailure("Commande réservée au staff autorisé.")

    for category, names in main.CATEGORY_COMMANDS.items():
        if name not in names:
            continue
        if await _has_manager_access(bot, interaction, category):
            return True
        raise app_commands.CheckFailure(
            f"Commande de gestion réservée aux responsables de la catégorie {category}."
        )

    if await _has_manager_access(bot, interaction, "complete"):
        return True
    raise app_commands.CheckFailure(
        "Commande non classée : accès administrateur appliqué par sécurité."
    )


def _force_help_public(bot: commands.Bot) -> None:
    command = bot.get_command("help")
    if command is None:
        return
    command.hidden = False
    command_checks = getattr(command, "checks", None)
    if isinstance(command_checks, list):
        command_checks.clear()
    app = getattr(command, "app_command", None)
    app_checks = getattr(app, "checks", None)
    if isinstance(app_checks, list):
        app_checks.clear()


def install(bot: commands.Bot) -> None:
    import main
    from . import slash_command_budget

    main.PUBLIC_COMMANDS = main.PUBLIC_COMMANDS | {"help", "ticket", "giveaway"}
    main.CATEGORY_COMMANDS["securite"] = (
        main.CATEGORY_COMMANDS.get("securite", frozenset())
        | {"panic", "blacklist-add", "blacklist-users", "syncbl"}
    )
    main.CATEGORY_COMMANDS["configuration"] = (
        main.CATEGORY_COMMANDS.get("configuration", frozenset())
        | {
            "setprefix", "setmodrole", "set-xp", "add-xp", "set-level-role",
            "remove-level-role", "reset-levels", "giveaway-reroll",
        }
    )
    main.KNOWN_PERMISSION_COMMANDS = (
        main.PUBLIC_COMMANDS
        | main.OWNER_ONLY_COMMANDS
        | main.CUSTOM_PERMISSION_COMMANDS
        | frozenset(main.DISCORD_PERMISSION_COMMANDS)
        | frozenset().union(*main.CATEGORY_COMMANDS.values())
    )

    _force_help_public(bot)

    tree = bot.tree
    if not getattr(tree, "_sentrix_interaction_policy_v2", False):
        original_check = tree.interaction_check

        async def guarded_interaction_check(_tree, interaction: discord.Interaction) -> bool:
            result = original_check(interaction)
            if hasattr(result, "__await__"):
                result = await result
            if result is False:
                return False
            return await _enforce(bot, interaction)

        # Conserver la preuve que le verrou central précédent reste dans la chaîne.
        guarded_interaction_check._sentrix_permission_guard = bool(
            getattr(original_check, "_sentrix_permission_guard", False)
        )
        tree.interaction_check = MethodType(guarded_interaction_check, tree)
        tree._sentrix_interaction_policy_v2 = True
        logger.info("Politique permissions slash fail-closed installée.")

    slash_command_budget.finalize(bot)
    _force_help_public(bot)
