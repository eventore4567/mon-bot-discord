"""Vérifications de permissions et de hiérarchie partagées par SentriX.

Les checks sont utilisés par les commandes hybrides (+ et /) et portent une métadonnée
lisible afin que +help puisse afficher la permission requise sans exécuter la commande.
"""
from __future__ import annotations

import discord
from discord.ext import commands

from utils.command_permissions import permission_label


class BotPermissionError(commands.CheckFailure):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class BotBlacklistedError(commands.CheckFailure):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _mark(predicate, label: str):
    predicate._sentrix_permission_label = label
    return predicate


async def is_verified_bot_owner(ctx: commands.Context) -> bool:
    from config import OWNER_IDS
    from database.db import PRIMARY_CREATOR_ID

    if ctx.author.id == PRIMARY_CREATOR_ID or ctx.author.id in OWNER_IDS:
        return True
    return await ctx.bot.db.is_bot_creator(ctx.author.id)


def is_bot_owner():
    async def predicate(ctx: commands.Context) -> bool:
        if await is_verified_bot_owner(ctx):
            return True
        raise BotPermissionError("Cette commande est réservée au **propriétaire global de SentriX**.")

    return commands.check(_mark(predicate, "Propriétaire global SentriX"))


def is_owner_or_admin():
    """Administrateur du serveur ou propriétaire global SentriX.

    Les anciens gestionnaires du bot par serveur ne donnent plus de droits d'administration.
    """
    async def predicate(ctx: commands.Context) -> bool:
        if await is_verified_bot_owner(ctx):
            return True
        if isinstance(ctx.author, discord.Member) and ctx.author.guild_permissions.administrator:
            return True
        raise BotPermissionError("Vous devez avoir la permission **Administrateur** pour utiliser cette commande.")

    return commands.check(_mark(predicate, "Administrateur"))


def is_owner_or_admin_for(category: str):
    """Compatibilité des anciens appels, sans privilège de gestionnaire de serveur."""
    async def predicate(ctx: commands.Context) -> bool:
        if await is_verified_bot_owner(ctx):
            return True
        if isinstance(ctx.author, discord.Member) and ctx.author.guild_permissions.administrator:
            return True
        raise BotPermissionError(
            f"Vous devez avoir la permission **Administrateur** pour cette fonction ({category})."
        )

    return commands.check(_mark(predicate, "Administrateur"))


def has_permission(permission: str):
    async def predicate(ctx: commands.Context) -> bool:
        if not isinstance(ctx.author, discord.Member):
            raise BotPermissionError("Cette commande doit être utilisée sur un serveur.")
        if getattr(ctx.author.guild_permissions, permission, False):
            return True
        label = permission_label(permission)
        raise BotPermissionError(
            "Vous ne pouvez pas utiliser cette commande.\n\n"
            f"**Permission requise :** {label}"
        )

    return commands.check(_mark(predicate, permission_label(permission)))


async def is_mod_or_permission(ctx: commands.Context, permission: str) -> bool:
    if not isinstance(ctx.author, discord.Member):
        return False
    if getattr(ctx.author.guild_permissions, permission, False):
        return True
    conf = await ctx.bot.db.get_guild_config(ctx.guild.id)
    if conf and conf["mod_role"]:
        role = ctx.guild.get_role(conf["mod_role"])
        if role and role in ctx.author.roles:
            return True
    return False


def has_permission_or_modrole(permission: str):
    async def predicate(ctx: commands.Context) -> bool:
        if await is_mod_or_permission(ctx, permission):
            return True
        label = permission_label(permission)
        raise BotPermissionError(
            "Vous ne pouvez pas utiliser cette commande.\n\n"
            f"**Permission requise :** {label} ou le rôle staff configuré"
        )

    return commands.check(_mark(predicate, f"{permission_label(permission)} ou rôle staff"))


def check_hierarchy(author: discord.Member, target: discord.Member) -> str | None:
    guild = author.guild
    if target.id == author.id:
        return "Vous ne pouvez pas effectuer cette action sur vous-même."
    if target.id == guild.owner_id:
        return "Vous ne pouvez pas sanctionner le propriétaire du serveur."
    if author.id == guild.owner_id:
        return None
    if target.top_role >= author.top_role:
        return "Vous ne pouvez pas sanctionner un membre ayant un rôle supérieur ou égal au vôtre."
    return None


def check_bot_hierarchy(guild: discord.Guild, target: discord.Member) -> str | None:
    me = guild.me
    if target.id == guild.owner_id:
        return "Je ne peux pas sanctionner le propriétaire du serveur."
    if target.top_role >= me.top_role:
        return "Mon rôle est trop bas dans la hiérarchie pour sanctionner ce membre."
    return None


async def can_use_embed_builder(ctx: commands.Context) -> bool:
    if await is_verified_bot_owner(ctx):
        return True
    if not isinstance(ctx.author, discord.Member):
        return False
    perms = ctx.author.guild_permissions
    if perms.manage_messages or perms.manage_guild:
        return True

    rows = await ctx.bot.db.fetchall(
        "SELECT role_id FROM embed_allowed_roles WHERE guild_id = ?",
        (ctx.guild.id,),
    )
    allowed_role_ids = {row["role_id"] for row in rows}
    return bool(allowed_role_ids and any(role.id in allowed_role_ids for role in ctx.author.roles))


def has_embed_permission():
    async def predicate(ctx: commands.Context) -> bool:
        if await can_use_embed_builder(ctx):
            return True
        raise BotPermissionError(
            "Il vous faut **Gérer les messages**, **Gérer le serveur** ou un rôle "
            "explicitement autorisé via `+embedconfig`."
        )

    return commands.check(_mark(predicate, "Gérer les messages / Gérer le serveur / rôle autorisé"))
