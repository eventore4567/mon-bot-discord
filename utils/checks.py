"""
Vérifications de permissions et de hiérarchie partagées par toutes les commandes.
Empêche notamment un membre du staff de sanctionner quelqu'un d'un rang égal ou supérieur.

Toutes les commandes sont des "hybrid commands" (discord.py) : elles fonctionnent à la
fois en slash command et en commande préfixée (+). Les checks ci-dessous utilisent donc
commands.Context, qui fonctionne dans les deux cas (ctx.interaction est défini pour le slash).
"""

import discord
from discord.ext import commands


class BotPermissionError(commands.CheckFailure):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class BotBlacklistedError(commands.CheckFailure):
    """Levée quand un utilisateur inscrit sur la liste noire GLOBALE d'utilisation du bot
    (voir /bl, cog Owner) essaie d'utiliser n'importe quelle commande, sur n'importe quel serveur."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


async def is_verified_bot_owner(ctx: commands.Context) -> bool:
    """Propriétaire configuré par OWNER_IDS ou créateur vérifié dans la base."""
    from config import OWNER_IDS

    if ctx.author.id in OWNER_IDS:
        return True
    return await ctx.bot.db.is_bot_creator(ctx.author.id)


def is_bot_owner():
    """Autorise le(s) propriétaire(s) du bot (base de données ou OWNER_IDS dans .env) — réservé aux
    réglages globaux qui affectent le bot partout : présence, identité, liste noire d'utilisation..."""

    async def predicate(ctx: commands.Context) -> bool:
        if await is_verified_bot_owner(ctx):
            return True
        raise BotPermissionError("Cette commande est réservée au **propriétaire du bot**.")

    return commands.check(predicate)


def is_owner_or_admin():
    """Autorise les administrateurs du serveur, les propriétaires du bot, ou un membre
    ajouté comme "gestionnaire du bot" (via /setup → page Gestionnaires)."""

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
    """Comme is_owner_or_admin(), mais un "gestionnaire du bot" (ni admin, ni propriétaire)
    doit EN PLUS posséder la catégorie de permission `category` pour passer ce check.
    Catégories possibles : voir MANAGER_CATEGORIES dans database/db.py
    ("configuration", "tickets", "moderation", "securite", "economie", "complete").

    Rétrocompatible : un gestionnaire à qui aucune catégorie précise n'a jamais été assignée
    (tous les gestionnaires ajoutés avant l'existence des permissions granulaires, ou ajoutés
    sans qu'un admin choisisse de catégorie) garde l'accès complet, exactement comme avant —
    voir Database.has_manager_permission(), qui renvoie True si aucune ligne n'existe pour ce
    gestionnaire. Les administrateurs et propriétaires du bot ne sont jamais concernés par
    cette restriction : ils gardent un accès total, comme avec is_owner_or_admin()."""

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
                f"« {category} » nécessaire pour cette commande. Un administrateur peut vous "
                "l'accorder via `/setup` → page Gestionnaires."
            )
        raise BotPermissionError("Vous devez être **administrateur** (ou gestionnaire du bot) pour utiliser cette commande.")

    return commands.check(predicate)


def has_permission(permission: str):
    """Vérifie qu'un membre possède une permission Discord donnée (ex: 'kick_members')."""

    async def predicate(ctx: commands.Context) -> bool:
        if not isinstance(ctx.author, discord.Member):
            raise BotPermissionError("Cette commande doit être utilisée sur un serveur.")
        if getattr(ctx.author.guild_permissions, permission, False):
            return True
        raise BotPermissionError(f"Il vous manque la permission `{permission}` pour utiliser cette commande.")

    return commands.check(predicate)


async def is_mod_or_permission(ctx: commands.Context, permission: str) -> bool:
    """Vrai si le membre a la permission Discord donnée OU le rôle de modérateur configuré."""
    if not isinstance(ctx.author, discord.Member):
        return False
    if getattr(ctx.author.guild_permissions, permission, False):
        return True
    db = ctx.bot.db
    conf = await db.get_guild_config(ctx.guild.id)
    if conf and conf["mod_role"]:
        role = ctx.guild.get_role(conf["mod_role"])
        if role and role in ctx.author.roles:
            return True
    return False


def has_permission_or_modrole(permission: str):
    """Autorise si le membre a la permission Discord ou le rôle staff configuré via /setmodrole."""

    async def predicate(ctx: commands.Context) -> bool:
        if await is_mod_or_permission(ctx, permission):
            return True
        raise BotPermissionError(
            f"Il vous manque la permission `{permission}` (ou le rôle staff configuré) pour utiliser cette commande."
        )

    return commands.check(predicate)


def check_hierarchy(author: discord.Member, target: discord.Member) -> str | None:
    """
    Vérifie que 'author' peut agir sur 'target'.
    Retourne un message d'erreur en français si l'action est interdite, sinon None.
    """
    guild = author.guild

    if target.id == author.id:
        return "Vous ne pouvez pas effectuer cette action sur vous-même."

    if target.id == guild.owner_id:
        return "Vous ne pouvez pas sanctionner le propriétaire du serveur."

    if author.id == guild.owner_id:
        return None  # Le propriétaire peut tout faire

    if target.top_role >= author.top_role:
        return "Vous ne pouvez pas sanctionner un membre ayant un rôle supérieur ou égal au vôtre."

    return None


def check_bot_hierarchy(guild: discord.Guild, target: discord.Member) -> str | None:
    """Vérifie que le bot lui-même peut agir sur la cible (rôle plus haut que le sien)."""
    me = guild.me
    if target.id == guild.owner_id:
        return "Je ne peux pas sanctionner le propriétaire du serveur."
    if target.top_role >= me.top_role:
        return "Mon rôle est trop bas dans la hiérarchie pour sanctionner ce membre."
    return None


async def can_use_embed_builder(ctx: commands.Context) -> bool:
    """Utilisée à la fois comme check de commande ET dans les vérifications d'interaction
    du créateur d'embeds (+embed) : Gérer les messages, Gérer le serveur, gestionnaire du
    bot avec la catégorie "embeds" (ou gestion complète), ou un rôle explicitement autorisé
    via +embedconfig. Le propriétaire du bot passe toujours."""
    if await is_verified_bot_owner(ctx):
        return True
    if not isinstance(ctx.author, discord.Member):
        return False
    perms = ctx.author.guild_permissions
    if perms.manage_messages or perms.manage_guild:
        return True
    db = ctx.bot.db
    if await db.is_bot_manager(ctx.guild.id, ctx.author.id):
        if await db.has_manager_permission(ctx.guild.id, ctx.author.id, "embeds"):
            return True
    rows = await db.fetchall("SELECT role_id FROM embed_allowed_roles WHERE guild_id = ?", (ctx.guild.id,))
    allowed_role_ids = {r["role_id"] for r in rows}
    if allowed_role_ids and any(r.id in allowed_role_ids for r in ctx.author.roles):
        return True
    return False


def has_embed_permission():
    """Check de commande pour +embed et son groupe de sous-commandes — voir
    can_use_embed_builder() pour le détail des règles."""

    async def predicate(ctx: commands.Context) -> bool:
        if await can_use_embed_builder(ctx):
            return True
        raise BotPermissionError(
            "Il vous faut la permission **Gérer les messages**, **Gérer le serveur**, être "
            "gestionnaire du bot (catégorie « Créateur d'embeds ») ou avoir un rôle autorisé "
            "via `+embedconfig` pour utiliser cette commande."
        )

    return commands.check(predicate)
