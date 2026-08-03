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


def is_bot_owner():
    """Autorise uniquement le(s) propriétaire(s) du bot (OWNER_IDS dans .env) — réservé aux
    réglages globaux qui affectent le bot partout : présence, identité, liste noire d'utilisation..."""

    async def predicate(ctx: commands.Context) -> bool:
        from config import OWNER_IDS

        if ctx.author.id in OWNER_IDS:
            return True
        raise BotPermissionError("Cette commande est réservée au **propriétaire du bot**.")

    return commands.check(predicate)


def is_owner_or_admin():
    """Autorise les administrateurs du serveur, les propriétaires du bot, ou un membre
    ajouté comme "gestionnaire du bot" (via /setup → page Gestionnaires)."""

    async def predicate(ctx: commands.Context) -> bool:
        from config import OWNER_IDS

        if ctx.author.id in OWNER_IDS:
            return True
        if isinstance(ctx.author, discord.Member) and ctx.author.guild_permissions.administrator:
            return True
        if ctx.guild is not None and await ctx.bot.db.is_bot_manager(ctx.guild.id, ctx.author.id):
            return True
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
