"""Rôles donnés à l'arrivée — jusqu'à MAX_ROLES, une seule source de vérité.

Stockage rétrocompatible : le premier rôle reste dans ``guild_config.autorole``
(lu par le dashboard, ``+setautorole`` et l'ancien code) ; les suivants vivent
dans ``welcome_autoroles``. Une table neuve plutôt que l'ancienne table
``autorole`` : plus personne n'y écrit depuis longtemps, et la relire aurait
réactivé en silence des rôles oubliés sur des serveurs existants.

Chaque rôle est revérifié AU MOMENT de l'arrivée, pas seulement au réglage : un
rôle qui a gagné « Administrateur » depuis, ou qui est passé au-dessus de
SentriX, n'est plus donné, et la raison part dans les journaux du bot.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

import discord

logger = logging.getLogger("bot.welcome-autoroles")

MAX_ROLES = 5

# Donner l'une de ces permissions à CHAQUE arrivant ouvre le serveur au premier
# compte jetable venu : un raid n'aurait même plus besoin de contourner la
# modération. Liste de cogs/security_tools.DANGEROUS_PERMISSIONS SANS
# « Mentionner @everyone » : Discord la met dans les permissions par défaut de
# tout rôle créé, la refuser aurait écarté des rôles « Membre » ordinaires.
DANGEROUS = (
    ("administrator", "Administrateur"),
    ("manage_guild", "Gérer le serveur"),
    ("manage_roles", "Gérer les rôles"),
    ("manage_channels", "Gérer les salons"),
    ("manage_webhooks", "Gérer les webhooks"),
    ("ban_members", "Bannir des membres"),
    ("kick_members", "Expulser des membres"),
    ("moderate_members", "Exclure temporairement"),
    ("manage_messages", "Gérer les messages"),
    ("manage_nicknames", "Gérer les pseudos"),
    ("manage_emojis_and_stickers", "Gérer les emojis"),
)


async def ensure_schema(db: Any) -> None:
    await db.execute(
        "CREATE TABLE IF NOT EXISTS welcome_autoroles ("
        "guild_id INTEGER NOT NULL, role_id INTEGER NOT NULL, position INTEGER NOT NULL DEFAULT 0, "
        "PRIMARY KEY (guild_id, role_id))"
    )


def role_problem(guild: discord.Guild, role: discord.Role | None) -> str | None:
    """Pourquoi ce rôle ne peut pas être donné à chaque arrivant (None = possible)."""
    if role is None:
        return "Ce rôle n'existe plus."
    if role.is_default():
        return "Le rôle @everyone ne peut pas être donné."
    if getattr(role, "managed", False):
        return f"{role.mention} est géré par une intégration ou un bot : personne ne peut le donner."
    dangerous = [label for name, label in DANGEROUS if getattr(role.permissions, name, False)]
    if dangerous:
        return (
            f"{role.mention} donne **{', '.join(dangerous[:3])}** : un rôle d'arrivée ne peut pas "
            "accorder de pouvoir de modération ou d'administration."
        )
    me = guild.me
    if me is None:
        return "SentriX n'est pas disponible dans le cache de ce serveur."
    if not (me.guild_permissions.manage_roles or me.guild_permissions.administrator):
        return "SentriX n'a pas la permission **Gérer les rôles**."
    if role >= me.top_role:
        return f"{role.mention} est au-dessus (ou au niveau) du rôle de SentriX : placez SentriX plus haut."
    return None


def _ids(values: Iterable[Any]) -> list[int]:
    out: list[int] = []
    for value in values:
        try:
            role_id = int(value)
        except (TypeError, ValueError):
            continue
        if role_id > 0 and role_id not in out:
            out.append(role_id)
    return out


async def configured_ids(bot: Any, guild_id: int) -> list[int]:
    """Rôle principal d'abord, puis les supplémentaires dans l'ordre choisi."""
    conf = await bot.db.get_guild_config(guild_id)
    try:
        primary = conf["autorole"] if conf else None
    except (KeyError, IndexError, TypeError):
        primary = None
    await ensure_schema(bot.db)
    rows = await bot.db.fetchall(
        "SELECT role_id FROM welcome_autoroles WHERE guild_id=? ORDER BY position, role_id", (guild_id,)
    )
    return _ids([primary, *(row["role_id"] for row in rows or ())])[:MAX_ROLES]


async def save(bot: Any, guild_id: int, role_ids: Iterable[Any]) -> list[int]:
    """Remplace la liste complète. Le premier rôle va dans guild_config.autorole."""
    ids = _ids(role_ids)[:MAX_ROLES]
    await ensure_schema(bot.db)
    await bot.db.set_guild_config(guild_id, "autorole", ids[0] if ids else None)
    await bot.db.execute("DELETE FROM welcome_autoroles WHERE guild_id=?", (guild_id,))
    for position, role_id in enumerate(ids[1:], start=1):
        await bot.db.execute(
            "INSERT INTO welcome_autoroles (guild_id, role_id, position) VALUES (?,?,?)",
            (guild_id, role_id, position),
        )
    return ids


async def clear(bot: Any, guild_id: int) -> None:
    await ensure_schema(bot.db)
    await bot.db.execute("DELETE FROM welcome_autoroles WHERE guild_id=?", (guild_id,))


async def apply(bot: Any, member: discord.Member) -> tuple[list[discord.Role], list[str]]:
    """Donne à ``member`` chaque rôle configuré encore valide.

    Renvoie (rôles donnés, raisons des rôles écartés). Un rôle refusé n'empêche
    pas les autres d'être donnés.
    """
    given: list[discord.Role] = []
    skipped: list[str] = []
    for role_id in await configured_ids(bot, member.guild.id):
        role = member.guild.get_role(role_id)
        problem = role_problem(member.guild, role)
        if problem:
            skipped.append(f"{role_id}: {problem}")
            continue
        if role in member.roles:
            continue
        try:
            await member.add_roles(role, reason="Rôle d'arrivée SentriX")
        except discord.HTTPException as exc:
            skipped.append(f"{role_id}: Discord a refusé ({exc.status})")
            continue
        given.append(role)
    if skipped:
        logger.warning("Rôles d'arrivée écartés guild=%s user=%s : %s", member.guild.id, member.id, " | ".join(skipped))
    return given, skipped
