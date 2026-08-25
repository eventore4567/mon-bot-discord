"""Checks métier partagés par SentriX.

La matrice globale d'accès vit dans ``cogs.permission_guard``. Les checks de ce fichier
restent des garde-fous locaux (hiérarchie, permission native, catégorie de gestionnaire)
et ne doivent jamais élargir la matrice globale.
"""
from __future__ import annotations

import discord
from discord.ext import commands


class BotPermissionError(commands.CheckFailure):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class BotBlacklistedError(commands.CheckFailure):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


async def is_verified_bot_owner(ctx: commands.Context) -> bool:
    from config import OWNER_IDS
    from database.db import PRIMARY_CREATOR_ID
    if ctx.author.id == PRIMARY_CREATOR_ID or ctx.author.id in OWNER_IDS:
        return True
    try:
        return bool(await ctx.bot.db.is_bot_creator(ctx.author.id))
    except Exception:
        # Un problème de DB ne doit jamais accorder un accès propriétaire.
        return False


def is_bot_owner():
    async def predicate(ctx: commands.Context) -> bool:
        if await is_verified_bot_owner(ctx):
            return True
        raise BotPermissionError("Cette commande est réservée au **propriétaire du bot**.")
    return commands.check(predicate)


def is_owner_or_admin():
    async def predicate(ctx: commands.Context) -> bool:
        if await is_verified_bot_owner(ctx):
            return True
        if isinstance(ctx.author, discord.Member) and ctx.author.guild_permissions.administrator:
            return True
        if ctx.guild is not None and await ctx.bot.db.is_bot_manager(ctx.guild.id, ctx.author.id):
            return True
        raise BotPermissionError("Vous devez être **administrateur** (ou gestionnaire du bot) pour utiliser cette commande.")
    return commands.check(predicate)


def is_owner_or_admin_for(category: str):
    async def predicate(ctx: commands.Context) -> bool:
        if await is_verified_bot_owner(ctx):
            return True
        if isinstance(ctx.author, discord.Member) and ctx.author.guild_permissions.administrator:
            return True
        if ctx.guild is not None and await ctx.bot.db.is_bot_manager(ctx.guild.id, ctx.author.id):
            if await ctx.bot.db.has_manager_permission(ctx.guild.id, ctx.author.id, category):
                return True
            raise BotPermissionError(
                "Vous êtes gestionnaire du bot, mais vous n'avez pas la permission "
                f"« {category} » nécessaire. Un administrateur peut l'accorder via `+setup`."
            )
        raise BotPermissionError("Vous devez être **administrateur** (ou gestionnaire du bot) pour utiliser cette commande.")
    return commands.check(predicate)


def has_permission(permission: str):
    async def predicate(ctx: commands.Context) -> bool:
        if not isinstance(ctx.author, discord.Member):
            raise BotPermissionError("Cette commande doit être utilisée sur un serveur.")
        if getattr(ctx.author.guild_permissions, permission, False):
            return True
        raise BotPermissionError(f"Il vous manque la permission `{permission}` pour utiliser cette commande.")
    return commands.check(predicate)


async def is_mod_or_permission(ctx: commands.Context, permission: str) -> bool:
    """Permission native, ou rôle modo uniquement pour les actions quotidiennes sûres."""
    if not isinstance(ctx.author, discord.Member) or ctx.guild is None:
        return False
    if getattr(ctx.author.guild_permissions, permission, False):
        return True
    try:
        from cogs.permission_guard import SAFE_MOD_ROLE_PERMISSIONS
    except Exception:
        SAFE_MOD_ROLE_PERMISSIONS = frozenset({
            "ban_members", "kick_members", "moderate_members", "manage_messages",
            "manage_nicknames", "move_members",
        })
    if permission not in SAFE_MOD_ROLE_PERMISSIONS:
        return False
    try:
        conf = await ctx.bot.db.get_guild_config(ctx.guild.id)
    except Exception:
        return False
    mod_role_id = conf["mod_role"] if conf and conf["mod_role"] else None
    if not mod_role_id:
        return False
    return any(int(getattr(role, "id", 0)) == int(mod_role_id) for role in ctx.author.roles)


def has_permission_or_modrole(permission: str):
    async def predicate(ctx: commands.Context) -> bool:
        if await is_mod_or_permission(ctx, permission):
            return True
        try:
            from cogs.permission_guard import SAFE_MOD_ROLE_PERMISSIONS
            fallback = permission in SAFE_MOD_ROLE_PERMISSIONS
        except Exception:
            fallback = False
        suffix = " (ou le rôle staff configuré)" if fallback else ""
        raise BotPermissionError(f"Il vous manque la permission `{permission}`{suffix} pour utiliser cette commande.")
    return commands.check(predicate)


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
    if me is None:
        return "SentriX ne peut pas vérifier sa hiérarchie pour le moment. Réessayez dans quelques secondes."
    if target.id == guild.owner_id:
        return "Je ne peux pas sanctionner le propriétaire du serveur."
    if target.top_role >= me.top_role:
        return "Mon rôle est trop bas dans la hiérarchie pour sanctionner ce membre."
    return None


async def can_use_embed_builder(ctx: commands.Context) -> bool:
    if await is_verified_bot_owner(ctx):
        return True
    if not isinstance(ctx.author, discord.Member) or ctx.guild is None:
        return False
    perms = ctx.author.guild_permissions
    if perms.manage_messages or perms.manage_guild or perms.administrator:
        return True
    db = ctx.bot.db
    try:
        if await db.is_bot_manager(ctx.guild.id, ctx.author.id):
            if await db.has_manager_permission(ctx.guild.id, ctx.author.id, "embeds"):
                return True
        rows = await db.fetchall("SELECT role_id FROM embed_allowed_roles WHERE guild_id = ?", (ctx.guild.id,))
    except Exception:
        return False
    allowed = {int(row["role_id"]) for row in rows}
    return any(int(role.id) in allowed for role in ctx.author.roles)


def has_embed_permission():
    async def predicate(ctx: commands.Context) -> bool:
        if await can_use_embed_builder(ctx):
            return True
        raise BotPermissionError(
            "Il vous faut **Gérer les messages**, **Gérer le serveur**, une autorisation de gestionnaire "
            "pour les embeds ou un rôle explicitement autorisé."
        )
    return commands.check(predicate)
