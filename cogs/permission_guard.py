"""Garde de permissions centrale pour SentriX.

Le bot possede deja des checks locaux dans ses cogs et un second verrou global pour les
commandes prefixees. Cette couche rend la meme politique obligatoire pour les commandes
slash/hybrides, puis force ``help`` a rester publique. Le principe est fail-closed : une
commande non classee reste reservee aux administrateurs/gestionnaires complets.

Ce module ne remplace pas les checks metier (hierarchie des roles, cible sanctionnable,
etc.). Il ajoute un verrou transversal qui s'applique avant eux.
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

logger = logging.getLogger("bot.permission-guard")


@dataclass(frozen=True, slots=True)
class AccessDecision:
    allowed: bool
    reason: str = ""
    policy: str = ""


def _policy_module(bot: commands.Bot):
    """Retourne le module qui porte la matrice de permissions du bot.

    Les ensembles de ``main.py`` peuvent etre enrichis dynamiquement par certains runtimes.
    Ils sont donc relus a chaque decision au lieu d'etre copies au chargement de ce module.
    """
    return sys.modules.get(bot.__class__.__module__)


def _policy_sets(bot: commands.Bot):
    module = _policy_module(bot)
    if module is None:
        return frozenset(), frozenset(), frozenset(), {}, {}
    public = frozenset(getattr(module, "PUBLIC_COMMANDS", frozenset()))
    owner_only = frozenset(getattr(module, "OWNER_ONLY_COMMANDS", frozenset()))
    custom = frozenset(getattr(module, "CUSTOM_PERMISSION_COMMANDS", frozenset()))
    discord_permissions = dict(getattr(module, "DISCORD_PERMISSION_COMMANDS", {}))
    categories = dict(getattr(module, "CATEGORY_COMMANDS", {}))
    return public, owner_only, custom, discord_permissions, categories


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
        # Ne jamais accorder un acces sensible lorsque la verification DB echoue.
        logger.exception("Verification proprietaire impossible pour user=%s", user_id)
        return False


def _member_permissions(author: Any):
    return getattr(author, "guild_permissions", None)


async def _is_manager_for(bot: commands.Bot, guild: Any, author: Any, category: str) -> bool:
    if guild is None or author is None:
        return False
    permissions = _member_permissions(author)
    if permissions is not None and bool(getattr(permissions, "administrator", False)):
        return True

    guild_id = getattr(guild, "id", None)
    user_id = getattr(author, "id", None)
    if guild_id is None or user_id is None:
        return False
    try:
        if not await bot.db.is_bot_manager(int(guild_id), int(user_id)):
            return False
        return bool(await bot.db.has_manager_permission(int(guild_id), int(user_id), category))
    except Exception:
        logger.exception(
            "Verification gestionnaire impossible (guild=%s user=%s category=%s)",
            guild_id,
            user_id,
            category,
        )
        return False


async def _has_discord_or_modrole_permission(
    bot: commands.Bot,
    guild: Any,
    author: Any,
    permission: str,
) -> bool:
    if guild is None or author is None:
        return False

    permissions = _member_permissions(author)
    if permissions is not None and bool(getattr(permissions, permission, False)):
        return True

    guild_id = getattr(guild, "id", None)
    user_id = getattr(author, "id", None)
    if guild_id is None or user_id is None:
        return False

    try:
        conf = await bot.db.get_guild_config(int(guild_id))
    except Exception:
        logger.exception("Lecture du role de moderation impossible pour guild=%s", guild_id)
        return False

    mod_role_id = conf["mod_role"] if conf and conf["mod_role"] else None
    if not mod_role_id:
        return False
    return any(int(getattr(role, "id", 0)) == int(mod_role_id) for role in getattr(author, "roles", ()))


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
    user_id = getattr(author, "id", None)
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
        logger.exception(
            "Verification createur d'embeds impossible (guild=%s user=%s)",
            guild_id,
            user_id,
        )
        return False

    allowed_role_ids = {int(row["role_id"]) for row in rows}
    return any(int(getattr(role, "id", 0)) in allowed_role_ids for role in getattr(author, "roles", ()))


async def evaluate_command_access(
    bot: commands.Bot,
    *,
    command_name: str,
    author: Any,
    guild: Any,
) -> AccessDecision:
    """Evalue la matrice centrale pour une racine de commande.

    L'ordre est volontaire : public -> owner-only -> bypass owner -> permissions ciblees ->
    categories de gestion -> fail-closed. Les commandes publiques restent utilisables en DM
    lorsqu'elles le supportent, tandis que toute commande sensible exige un serveur ou le
    proprietaire verifie du bot.
    """
    name = _normalise_name(command_name)
    if not name:
        return AccessDecision(False, "Commande impossible a identifier.", "invalid")

    public, owner_only, custom, discord_permissions, categories = _policy_sets(bot)
    user_id = getattr(author, "id", None)
    owner = bool(user_id is not None and await _is_verified_owner(bot, int(user_id)))

    if name in public:
        return AccessDecision(True, policy="public")

    if name in owner_only:
        if owner:
            return AccessDecision(True, policy="owner")
        return AccessDecision(
            False,
            "Cette commande est reservee au proprietaire verifie de SentriX.",
            "owner",
        )

    # Le proprietaire verifie garde un acces de secours a toutes les fonctions du bot.
    if owner:
        return AccessDecision(True, policy="owner-bypass")

    if name in custom:
        if await _can_use_embed_builder(bot, guild, author):
            return AccessDecision(True, policy="custom")
        return AccessDecision(
            False,
            "Cette commande est reservee au staff autorise a creer des embeds.",
            "custom",
        )

    required_permission = discord_permissions.get(name)
    if required_permission is not None:
        if await _has_discord_or_modrole_permission(bot, guild, author, required_permission):
            return AccessDecision(True, policy=f"discord:{required_permission}")
        return AccessDecision(
            False,
            "Cette commande est reservee au staff autorise. "
            f"Permission requise : `{required_permission}` ou role de moderation configure.",
            f"discord:{required_permission}",
        )

    for category, names in categories.items():
        if name not in names:
            continue
        if await _is_manager_for(bot, guild, author, category):
            return AccessDecision(True, policy=f"manager:{category}")
        return AccessDecision(
            False,
            "Cette commande de gestion est reservee aux administrateurs ou a un "
            f"gestionnaire autorise pour la categorie `{category}`.",
            f"manager:{category}",
        )

    # Fail-closed : une future commande non classee ne devient jamais publique par oubli.
    if await _is_manager_for(bot, guild, author, "complete"):
        return AccessDecision(True, policy="fail-closed-admin")
    return AccessDecision(
        False,
        "Cette commande n'a pas encore de niveau d'acces public valide. "
        "Elle est reservee aux administrateurs par securite.",
        "fail-closed",
    )


async def _interaction_blacklist_reason(bot: commands.Bot, author: Any) -> str | None:
    user_id = getattr(author, "id", None)
    if user_id is None:
        return None
    if await _is_verified_owner(bot, int(user_id)):
        return None
    cache = getattr(bot, "blacklist_cache", {})
    reason = cache.get(int(user_id)) if isinstance(cache, dict) else None
    if reason is None:
        return None
    return str(reason or "Aucune raison fournie")


async def evaluate_interaction_access(bot: commands.Bot, interaction: discord.Interaction) -> AccessDecision:
    """Meme verrou pour les commandes slash, avec blacklist globale en amont."""
    reason = await _interaction_blacklist_reason(bot, getattr(interaction, "user", None))
    if reason is not None:
        return AccessDecision(
            False,
            f"Vous n'etes pas autorise a utiliser SentriX. Raison : {reason}",
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
        title="SENTRIX / ACCES REFUSE",
        description=decision.reason or "Vous n'avez pas acces a cette commande.",
        colour=discord.Colour(0xED4245),
    )
    embed.set_footer(text="SentriX | Permissions securisees")
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
    """Retire uniquement les checks locaux accidentels de ``help``.

    Le cooldown global, la blacklist globale et la matrice centrale restent actifs. Cela
    garantit qu'un membre normal peut ouvrir l'aide sans transformer une commande sensible
    en commande publique.
    """
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
    """Installe une seule fois les verrous prefixe + slash sur une instance de bot."""
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
    # setup_hook() ajoutera ce callback comme check global apres le chargement des cogs.
    # En remplaçant la methode sur l'instance avant ce moment, prefixe et slash partagent
    # exactement la meme matrice.
    bot.global_permission_check = prefix_permission_guard

    original_tree_check = bot.tree.interaction_check

    async def slash_permission_guard(interaction: discord.Interaction) -> bool:
        previous = original_tree_check(interaction)
        if inspect.isawaitable(previous):
            previous = await previous
        if previous is False:
            return False
        if interaction.type is not discord.InteractionType.application_command:
            return True

        decision = await evaluate_interaction_access(bot, interaction)
        if decision.allowed:
            return True

        logger.warning(
            "Commande slash refusee par la matrice centrale (command=%s user=%s guild=%s policy=%s)",
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
        "Permissions SentriX renforcees : matrice unique prefixe/slash, fail-closed, blacklist slash et +help public."
    )
