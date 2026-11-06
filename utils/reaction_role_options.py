"""Options persistantes et application sûre des rôles par réaction."""

from __future__ import annotations

import time
from contextvars import ContextVar

import discord

SCHEMA = """CREATE TABLE IF NOT EXISTS sentrix_reaction_role_options (
 guild_id BIGINT NOT NULL, message_id BIGINT NOT NULL, single_role INTEGER NOT NULL DEFAULT 0,
 remove_on_unreact INTEGER NOT NULL DEFAULT 1, required_role_id BIGINT NOT NULL DEFAULT 0,
 PRIMARY KEY(guild_id,message_id))"""
WARN_SCHEMA = """CREATE TABLE IF NOT EXISTS sentrix_reaction_role_warnings (
 guild_id BIGINT PRIMARY KEY, notified_at BIGINT NOT NULL)"""


# Autorisation locale à la tâche : un retrait demandé par réaction ne devient
# jamais une exemption générale aux protections du propriétaire.
_SELF_SERVICE_REMOVAL = ContextVar("sentrix_reaction_role_removal", default=None)


def voluntary_removal_allowed(member, roles):
    from cogs.economy import _self_assignable_role_error

    scope = _SELF_SERVICE_REMOVAL.get()
    return bool(
        scope
        and scope[:2] == (member.guild.id, member.id)
        and roles
        and {r.id for r in roles} <= scope[2]
        and all(_self_assignable_role_error(member.guild, r) is None for r in roles)
    )


async def _remove_self_service_roles(member, roles, *, guild_id, reason):
    token = _SELF_SERVICE_REMOVAL.set((guild_id, member.id, {r.id for r in roles}))
    try:
        await member.remove_roles(*roles, reason=reason)
    finally:
        _SELF_SERVICE_REMOVAL.reset(token)


async def options(bot, guild_id, message_id):
    await bot.db.execute(SCHEMA)
    row = await bot.db.fetchone(
        "SELECT * FROM sentrix_reaction_role_options WHERE guild_id=? AND message_id=?",
        (guild_id, message_id),
    )
    return (
        dict(row)
        if row
        else {"single_role": 0, "remove_on_unreact": 1, "required_role_id": 0}
    )


async def save_options(bot, guild_id, message_id, updates):
    from utils import config_journal

    old = await options(bot, guild_id, message_id)
    if not set(updates) <= {"single_role", "remove_on_unreact", "required_role_id"}:
        raise ValueError("Option inconnue")
    new = {**old, **updates}
    await bot.db.execute(
        "INSERT INTO sentrix_reaction_role_options (guild_id,message_id,single_role,remove_on_unreact,required_role_id) VALUES (?,?,?,?,?) ON CONFLICT(guild_id,message_id) DO UPDATE SET single_role=excluded.single_role,remove_on_unreact=excluded.remove_on_unreact,required_role_id=excluded.required_role_id",
        (
            guild_id,
            message_id,
            new["single_role"],
            new["remove_on_unreact"],
            new["required_role_id"],
        ),
    )
    for name, value in updates.items():
        await config_journal.record(
            bot.db, guild_id, f"reaction_panel.{message_id}.{name}", old[name], value
        )


async def warn_owner(bot, guild, role):
    await bot.db.execute(WARN_SCHEMA)
    now = int(time.time())
    cursor = await bot.db.execute(
        "INSERT INTO sentrix_reaction_role_warnings (guild_id,notified_at) VALUES (?,?) ON CONFLICT(guild_id) DO UPDATE SET notified_at=excluded.notified_at WHERE sentrix_reaction_role_warnings.notified_at <= ?",
        (guild.id, now, now - 21600),
    )
    if cursor.rowcount < 1:
        return
    try:
        owner = guild.owner or await guild.fetch_member(guild.owner_id)
        await owner.send(
            f"SentriX ne peut pas attribuer le rôle {role.name}. Paramètres du serveur → Rôles → glisse le rôle de SentriX au-dessus de {role.mention}. Vérifiez aussi sa permission Gérer les rôles."
        )
    except (discord.Forbidden, discord.HTTPException):
        pass


async def apply_reaction(bot, payload, row, *, adding):
    from cogs.economy import _self_assignable_role_error

    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return
    member = getattr(payload, "member", None) or guild.get_member(payload.user_id)
    if member is None:
        try:
            member = await guild.fetch_member(payload.user_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return
    if member.bot:
        return
    role = guild.get_role(row["role_id"])
    if role is None:
        return
    settings = await options(bot, guild.id, payload.message_id)
    if not adding and not settings["remove_on_unreact"]:
        return
    me = guild.me
    if me is None:
        return
    if not me.guild_permissions.manage_roles or role >= me.top_role:
        return await warn_owner(bot, guild, role)
    if adding and _self_assignable_role_error(guild, role):
        return
    try:
        if adding:
            required = int(settings["required_role_id"] or 0)
            if required and required not in {r.id for r in member.roles}:
                channel = guild.get_channel(payload.channel_id)
                if channel:
                    message = await channel.fetch_message(payload.message_id)
                    await message.remove_reaction(payload.emoji, member)
                return
            if settings["single_role"]:
                rows = await bot.db.fetchall(
                    "SELECT role_id,emoji FROM reaction_roles WHERE guild_id=? AND message_id=?",
                    (guild.id, payload.message_id),
                )
                others = [
                    r
                    for item in rows
                    if item["role_id"] != role.id
                    and (r := guild.get_role(item["role_id"])) is not None
                    and r in member.roles
                ]
                if others:
                    await _remove_self_service_roles(
                        member,
                        others,
                        guild_id=guild.id,
                        reason="Un seul rôle par panneau",
                    )
                channel = guild.get_channel(payload.channel_id)
                if channel:
                    message = await channel.fetch_message(payload.message_id)
                    for item in rows:
                        if item["role_id"] != role.id:
                            await message.remove_reaction(item["emoji"], member)
            await member.add_roles(role, reason="Rôle sur réaction")
        else:
            await _remove_self_service_roles(
                member, [role], guild_id=guild.id, reason="Retrait rôle sur réaction"
            )
    except discord.Forbidden:
        await warn_owner(bot, guild, role)
    except (discord.HTTPException, discord.NotFound):
        pass


async def register_legacy_panel(
    bot, *, guild_id, channel_id, message_id, mappings, creator_id, created_at
):
    """Les anciens constructeurs rejoignent le même gestionnaire et les mêmes règles."""
    await bot.db.execute(
        "INSERT INTO reaction_role_panels (guild_id,channel_id,message_id,title,description,created_by,created_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(guild_id,message_id) DO NOTHING",
        (
            guild_id,
            channel_id,
            message_id,
            "Choisissez vos rôles",
            "Cliquez sur les réactions pour prendre vos rôles.",
            creator_id,
            created_at,
        ),
    )
    for mapping in mappings:
        await bot.db.execute(
            "INSERT INTO reaction_roles (guild_id,channel_id,message_id,emoji,emoji_key,role_id,label,created_by) SELECT ?,?,?,?,?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM reaction_roles WHERE guild_id=? AND message_id=? AND emoji_key=?)",
            (
                guild_id,
                channel_id,
                message_id,
                mapping["emoji"],
                mapping["key"],
                mapping["role_id"],
                "",
                creator_id,
                guild_id,
                message_id,
                mapping["key"],
            ),
        )


async def import_legacy_panels(bot, guild_id):
    import json
    import sqlite3

    for table, extra in (
        ("sentrix_role_panels", " AND mode='reaction'"),
        ("sentrix_reaction_role_panels", ""),
    ):
        try:
            rows = await bot.db.fetchall(
                f"SELECT * FROM {table} WHERE guild_id=?" + extra, (guild_id,)
            )
        except sqlite3.OperationalError:
            continue
        for row in rows:
            existing = await bot.db.fetchone(
                "SELECT message_id FROM reaction_role_panels WHERE guild_id=? AND message_id=?",
                (guild_id, row["message_id"]),
            )
            if existing:
                continue
            try:
                mappings = json.loads(row["mappings_json"] or "[]")
            except (ValueError, TypeError):
                continue
            await register_legacy_panel(
                bot,
                guild_id=guild_id,
                channel_id=row["channel_id"],
                message_id=row["message_id"],
                mappings=mappings,
                creator_id=row["created_by"],
                created_at=row["created_at"],
            )
