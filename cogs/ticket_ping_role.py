"""Rôles d'accès et de ping des tickets.

Ce module conserve la compatibilité avec l'ancien rôle global de ping, mais il porte
maintenant le réglage canonique par panel/type :
- rôles d'accès : voient et peuvent répondre au ticket, sans permission de modération ;
- rôles à ping : uniquement mentionnés à l'ouverture ;
- le rôle staff historique du type reste le rôle de gestion des boutons.

Un réglage de type surcharge celui du panel. Sans réglage moderne, le comportement
historique (rôle global de ping puis staff_role_id/mention_staff) est conservé.
"""

from __future__ import annotations

import json
import logging

import discord
from discord.ext import commands

logger = logging.getLogger("bot.ticket-ping-role")
_RUNTIME_INSTALLED = False
_SETUP_INSTALLED = False


def _normalise_role_ids(values) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    for value in values or []:
        try:
            role_id = int(value)
        except (TypeError, ValueError):
            continue
        if role_id <= 0 or role_id in seen:
            continue
        seen.add(role_id)
        result.append(role_id)
    return result[:25]


async def _ensure_table(bot: commands.Bot) -> None:
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_ping_settings (
            guild_id INTEGER PRIMARY KEY,
            role_id INTEGER,
            updated_at INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_role_rules (
            guild_id INTEGER NOT NULL,
            panel_id INTEGER NOT NULL,
            type_id INTEGER NOT NULL DEFAULT 0,
            access_role_ids_json TEXT NOT NULL DEFAULT '[]',
            ping_role_ids_json TEXT NOT NULL DEFAULT '[]',
            updated_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, panel_id, type_id)
        )
        """
    )


async def get_ticket_ping_role_id(bot: commands.Bot, guild_id: int) -> int | None:
    await _ensure_table(bot)
    row = await bot.db.fetchone(
        "SELECT role_id FROM ticket_ping_settings WHERE guild_id = ?",
        (guild_id,),
    )
    if not row or not row["role_id"]:
        return None
    return int(row["role_id"])


async def set_ticket_ping_role_id(bot: commands.Bot, guild_id: int, role_id: int | None) -> None:
    from database.db import now
    await _ensure_table(bot)
    await bot.db.execute(
        """
        INSERT INTO ticket_ping_settings (guild_id, role_id, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            role_id = excluded.role_id,
            updated_at = excluded.updated_at
        """,
        (guild_id, role_id, now()),
    )


def _decode_ids(raw) -> list[int]:
    if not raw:
        return []
    try:
        return _normalise_role_ids(json.loads(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


async def get_ticket_role_rules(bot: commands.Bot, guild_id: int, panel_id: int, type_id: int = 0) -> dict:
    await _ensure_table(bot)
    row = await bot.db.fetchone(
        """SELECT access_role_ids_json, ping_role_ids_json FROM ticket_role_rules
        WHERE guild_id = ? AND panel_id = ? AND type_id = ?""",
        (guild_id, panel_id, type_id),
    )
    if not row:
        return {"configured": False, "access_role_ids": [], "ping_role_ids": []}
    return {
        "configured": True,
        "access_role_ids": _decode_ids(row["access_role_ids_json"]),
        "ping_role_ids": _decode_ids(row["ping_role_ids_json"]),
    }


async def get_effective_ticket_role_rules(bot: commands.Bot, guild_id: int, panel_id: int, type_id: int) -> dict:
    own = await get_ticket_role_rules(bot, guild_id, panel_id, type_id)
    if own["configured"]:
        own["source"] = "type"
        return own
    parent = await get_ticket_role_rules(bot, guild_id, panel_id, 0)
    parent["source"] = "panel" if parent["configured"] else "legacy"
    return parent


async def set_ticket_role_rules(
    bot: commands.Bot,
    guild_id: int,
    panel_id: int,
    *,
    type_id: int = 0,
    access_role_ids=None,
    ping_role_ids=None,
) -> None:
    from database.db import now
    await _ensure_table(bot)
    access = _normalise_role_ids(access_role_ids)
    ping = _normalise_role_ids(ping_role_ids)
    await bot.db.execute(
        """INSERT INTO ticket_role_rules
        (guild_id, panel_id, type_id, access_role_ids_json, ping_role_ids_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(guild_id, panel_id, type_id) DO UPDATE SET
            access_role_ids_json=excluded.access_role_ids_json,
            ping_role_ids_json=excluded.ping_role_ids_json,
            updated_at=excluded.updated_at""",
        (guild_id, panel_id, type_id, json.dumps(access), json.dumps(ping), now()),
    )


async def delete_ticket_role_rules(bot: commands.Bot, guild_id: int, panel_id: int, type_id: int | None = None) -> None:
    await _ensure_table(bot)
    if type_id is None:
        await bot.db.execute(
            "DELETE FROM ticket_role_rules WHERE guild_id = ? AND panel_id = ?",
            (guild_id, panel_id),
        )
    else:
        await bot.db.execute(
            "DELETE FROM ticket_role_rules WHERE guild_id = ? AND panel_id = ? AND type_id = ?",
            (guild_id, panel_id, type_id),
        )


def valid_guild_roles(guild: discord.Guild, role_ids) -> list[discord.Role]:
    roles: list[discord.Role] = []
    for role_id in _normalise_role_ids(role_ids):
        role = guild.get_role(role_id)
        if role is None or role.is_default() or role.managed:
            continue
        roles.append(role)
    return roles


async def _resolve_ping_role(bot: commands.Bot, guild: discord.Guild) -> discord.Role | None:
    role_id = await get_ticket_ping_role_id(bot, guild.id)
    if not role_id:
        return None
    role = guild.get_role(role_id)
    if role is not None and not role.is_default() and not role.managed:
        return role
    logger.warning("Rôle ping tickets invalide (%s) sur %s ; retour au rôle staff du type.", role_id, guild.id)
    try:
        await set_ticket_ping_role_id(bot, guild.id, None)
    except Exception:
        logger.exception("Impossible de nettoyer le rôle ping tickets invalide %s sur %s.", role_id, guild.id)
    return None


def _ticket_value(ticket_type, key: str, default=None):
    try:
        return ticket_type[key]
    except (KeyError, TypeError, IndexError):
        return default


async def _fallback_staff_ping(channel: discord.TextChannel, guild: discord.Guild, ticket_type) -> None:
    if not _ticket_value(ticket_type, "mention_staff", 0):
        return
    staff_role_id = _ticket_value(ticket_type, "staff_role_id")
    staff_role = guild.get_role(int(staff_role_id)) if staff_role_id else None
    if staff_role is None or staff_role.is_default():
        return
    try:
        await channel.send(
            f"{staff_role.mention} — nouveau ticket à prendre en charge.",
            allowed_mentions=discord.AllowedMentions(everyone=False, users=False, roles=[staff_role], replied_user=False),
        )
    except discord.HTTPException:
        logger.exception("Le ping configuré ET le ping staff de secours ont échoué dans %s.", channel.id)


async def _grant_access_roles(channel: discord.TextChannel, roles: list[discord.Role]) -> None:
    for role in roles:
        overwrite = channel.overwrites_for(role)
        overwrite.view_channel = True
        overwrite.send_messages = True
        overwrite.read_message_history = True
        overwrite.attach_files = True
        overwrite.embed_links = True
        try:
            await channel.set_permissions(role, overwrite=overwrite, reason="Accès ticket configuré depuis SentriX")
        except discord.HTTPException:
            logger.exception("Impossible d'accorder l'accès ticket au rôle %s dans %s.", role.id, channel.id)


async def _ping_roles(channel: discord.TextChannel, roles: list[discord.Role]) -> None:
    if not roles:
        return
    try:
        await channel.send(
            " ".join(role.mention for role in roles) + " — nouveau ticket à prendre en charge.",
            allowed_mentions=discord.AllowedMentions(everyone=False, users=False, roles=roles, replied_user=False),
        )
    except discord.HTTPException:
        logger.exception("Impossible de ping les rôles %s dans %s.", [r.id for r in roles], channel.id)


def install_ticket_runtime(bot: commands.Bot) -> None:
    global _RUNTIME_INSTALLED
    if _RUNTIME_INSTALLED:
        return
    from . import tickets
    original_create_ticket = tickets.Tickets.create_ticket

    async def create_ticket_with_configured_roles(self, interaction, ticket_type, answers):
        guild = interaction.guild
        if guild is None:
            return await original_create_ticket(self, interaction, ticket_type, answers)

        panel_id = int(_ticket_value(ticket_type, "panel_id", 0) or 0)
        type_id = int(_ticket_value(ticket_type, "id", 0) or 0)
        rules = {"configured": False, "access_role_ids": [], "ping_role_ids": [], "source": "legacy"}
        global_ping_role: discord.Role | None = None
        before_id = 0
        try:
            if panel_id and type_id:
                rules = await get_effective_ticket_role_rules(self.bot, guild.id, panel_id, type_id)
            if not rules["configured"]:
                global_ping_role = await _resolve_ping_role(self.bot, guild)
            before = await self.bot.db.fetchone(
                "SELECT COALESCE(MAX(id), 0) AS last_id FROM tickets WHERE guild_id = ?",
                (guild.id,),
            )
            before_id = int(before["last_id"] if before else 0)
        except Exception:
            logger.exception("Impossible de préparer les rôles du ticket sur %s ; historique conservé.", guild.id)

        custom_ping_roles = valid_guild_roles(guild, rules["ping_role_ids"])
        access_roles = valid_guild_roles(guild, rules["access_role_ids"])
        suppress_legacy_staff_ping = bool(rules["configured"] or global_ping_role is not None)
        effective_type = ticket_type
        if suppress_legacy_staff_ping:
            try:
                effective_type = dict(ticket_type)
                effective_type["mention_staff"] = 0
            except Exception:
                effective_type = ticket_type
                suppress_legacy_staff_ping = False

        result = await original_create_ticket(self, interaction, effective_type, answers)
        if not panel_id or not type_id:
            return result
        try:
            created = await self.bot.db.fetchone(
                """SELECT id, channel_id FROM tickets
                WHERE guild_id = ? AND user_id = ? AND type_id = ? AND id > ?
                ORDER BY id DESC LIMIT 1""",
                (guild.id, interaction.user.id, type_id, before_id),
            )
            if not created:
                return result
            channel = guild.get_channel(int(created["channel_id"]))
            if not isinstance(channel, discord.TextChannel):
                return result
            await _grant_access_roles(channel, access_roles)
            if rules["configured"]:
                await _ping_roles(channel, custom_ping_roles)
            elif global_ping_role is not None:
                await _ping_roles(channel, [global_ping_role])
        except Exception:
            logger.exception("Erreur non bloquante après création du ticket lors de l'application des rôles.")
            if suppress_legacy_staff_ping and "channel" in locals() and isinstance(channel, discord.TextChannel):
                try:
                    await _fallback_staff_ping(channel, guild, ticket_type)
                except Exception:
                    logger.exception("Fallback staff du ticket impossible.")
        return result

    tickets.Tickets.create_ticket = create_ticket_with_configured_roles
    _RUNTIME_INSTALLED = True
    logger.info("Rôles d'accès/ping des tickets activés.")


def install_setup_ui(bot: commands.Bot) -> None:
    global _SETUP_INSTALLED
    if _SETUP_INSTALLED:
        return
    from . import configuration
    original_build_embed = configuration.SetupView.build_embed
    original_render_page = configuration.SetupView.render_page

    async def build_embed(self):
        embed = await original_build_embed(self)
        if self.page < 0:
            return embed
        try:
            step = configuration.SETUP_STEPS[self.page]
        except (IndexError, TypeError):
            return embed
        if step["key"] != "tickets":
            return embed
        try:
            role_id = await get_ticket_ping_role_id(self.bot, self.guild_id)
        except Exception:
            role_id = None
        guild = self._guild()
        role = guild.get_role(role_id) if guild and role_id else None
        if role is not None and (role.is_default() or role.managed):
            role = None
        embed.add_field(
            name="Rôle ping global (fallback)",
            value=role.mention if role else "*Aucun — les réglages de chaque panel/type sont prioritaires.*",
            inline=False,
        )
        return embed

    def render_page(self):
        original_render_page(self)
        if self.page < 0:
            return
        try:
            step = configuration.SETUP_STEPS[self.page]
        except (IndexError, TypeError):
            return
        if step["key"] != "tickets":
            return
        role_select = discord.ui.RoleSelect(placeholder="Choisir le rôle ping global de secours", min_values=1, max_values=1, row=1)

        async def role_callback(interaction: discord.Interaction):
            role = role_select.values[0]
            if role.id == interaction.guild.default_role.id or role.managed:
                return await interaction.response.send_message("Ce rôle ne peut pas être utilisé pour les tickets.", ephemeral=True)
            await set_ticket_ping_role_id(self.bot, self.guild_id, role.id)
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)

        role_select.callback = role_callback
        self.add_item(role_select)
        clear_button = discord.ui.Button(label="Retirer le rôle ping global", style=discord.ButtonStyle.secondary, row=2)

        async def clear_callback(interaction: discord.Interaction):
            await set_ticket_ping_role_id(self.bot, self.guild_id, None)
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)

        clear_button.callback = clear_callback
        self.add_item(clear_button)

    configuration.SetupView.build_embed = build_embed
    configuration.SetupView.render_page = render_page
    _SETUP_INSTALLED = True


__all__ = [
    "delete_ticket_role_rules",
    "get_effective_ticket_role_rules",
    "get_ticket_ping_role_id",
    "get_ticket_role_rules",
    "install_setup_ui",
    "install_ticket_runtime",
    "set_ticket_ping_role_id",
    "set_ticket_role_rules",
    "valid_guild_roles",
]
