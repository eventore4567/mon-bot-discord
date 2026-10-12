"""Rôles automatiques de modération : attribution explicitement configurée.

Une exclusion de giveaway peut ajouter un rôle choisi dans /setup. À la levée
de l'exclusion, on retire UNIQUEMENT un rôle réellement attribué par SentriX.
Aucune création de rôle, aucun changement de hiérarchie, aucun défaut implicite.
"""
from __future__ import annotations

import logging
import discord
from discord.ext import commands

logger = logging.getLogger("bot.auto-role-rules")
GIVEAWAY_ACTION = "giveaway_blacklist"

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS automatic_role_rules (
        guild_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        role_id INTEGER NOT NULL,
        PRIMARY KEY (guild_id, action)
    )""",
    """CREATE TABLE IF NOT EXISTS automatic_role_assignments (
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        role_id INTEGER NOT NULL,
        PRIMARY KEY (guild_id, user_id, action)
    )""",
)


async def ensure_schema(bot: commands.Bot) -> None:
    for sql in _SCHEMA:
        await bot.db.execute(sql)


async def giveaway_role_id(bot: commands.Bot, guild_id: int) -> int | None:
    await ensure_schema(bot)
    row = await bot.db.fetchone(
        "SELECT role_id FROM automatic_role_rules WHERE guild_id=? AND action=?",
        (guild_id, GIVEAWAY_ACTION),
    )
    return int(row["role_id"]) if row else None


async def set_giveaway_role(bot: commands.Bot, guild_id: int, role_id: int | None) -> None:
    await ensure_schema(bot)
    if role_id is None:
        await bot.db.execute(
            "DELETE FROM automatic_role_rules WHERE guild_id=? AND action=?",
            (guild_id, GIVEAWAY_ACTION),
        )
        return
    await bot.db.execute(
        "INSERT INTO automatic_role_rules (guild_id, action, role_id) VALUES (?, ?, ?) "
        "ON CONFLICT (guild_id, action) DO UPDATE SET role_id=excluded.role_id",
        (guild_id, GIVEAWAY_ACTION, int(role_id)),
    )


def _manageable(guild: discord.Guild, role: discord.Role | None) -> bool:
    me = guild.me
    if not me or role is None:
        return False
    return (
        role != guild.default_role
        and not role.managed
        and (me.guild_permissions.manage_roles or me.guild_permissions.administrator)
        and role < me.top_role
    )


async def sync_giveaway_blacklist(
    bot: commands.Bot, member: discord.Member, *, excluded: bool,
) -> str | None:
    """Synchronise le rôle ; ne modifie jamais un rôle pris autrement.

    Une erreur de permissions n'empêche PAS l'écriture de la vraie blacklist :
    on retourne alors une explication visible au modérateur.
    """
    guild = member.guild
    await ensure_schema(bot)
    if excluded:
        role_id = await giveaway_role_id(bot, guild.id)
        if role_id is None:
            return None
        role = guild.get_role(role_id)
        if not _manageable(guild, role):
            return "⚠️ Rôle d'exclusion non attribué : rôle absent ou permissions insuffisantes."
        if role in member.roles:
            return "ℹ️ Ce membre possédait déjà le rôle : aucun doublon."
        try:
            await member.add_roles(role, reason="Exclusion giveaways via SentriX")
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Attribution du rôle d'exclusion refusée, guild=%s", guild.id)
            return "⚠️ Exclusion enregistrée, mais Discord a refusé l'ajout du rôle."
        await bot.db.execute(
            "INSERT INTO automatic_role_assignments (guild_id,user_id,action,role_id) "
            "VALUES (?,?,?,?) ON CONFLICT(guild_id,user_id,action) "
            "DO UPDATE SET role_id=excluded.role_id",
            (guild.id, member.id, GIVEAWAY_ACTION, role.id),
        )
        return f"🏷️ Rôle {role.mention} attribué automatiquement."

    tracked = await bot.db.fetchone(
        "SELECT role_id FROM automatic_role_assignments "
        "WHERE guild_id=? AND user_id=? AND action=?",
        (guild.id, member.id, GIVEAWAY_ACTION),
    )
    if not tracked:
        return None
    role = guild.get_role(int(tracked["role_id"]))
    if role in member.roles:
        if not _manageable(guild, role):
            return "⚠️ Exclusion levée, mais SentriX ne peut plus retirer son ancien rôle."
        try:
            await member.remove_roles(role, reason="Fin d'exclusion giveaways via SentriX")
        except (discord.Forbidden, discord.HTTPException):
            return "⚠️ Exclusion levée, mais Discord a refusé le retrait du rôle."
    await bot.db.execute(
        "DELETE FROM automatic_role_assignments WHERE guild_id=? AND user_id=? AND action=?",
        (guild.id, member.id, GIVEAWAY_ACTION),
    )
    return "✅ Rôle automatique retiré."


class AutomaticRoleRules(commands.Cog):
    """Configuration du module de rôles automatiques, sans commande publique."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot


async def setup(bot: commands.Bot):
    await ensure_schema(bot)
    await bot.add_cog(AutomaticRoleRules(bot))
