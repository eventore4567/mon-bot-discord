"""Platform V4 — opérations, confidentialité, économie, automatisations et outils serveur.

Cette couche regroupe les fonctions qui manquaient au bot sans ajouter de nouvelles
commandes slash : le pilotage se fait principalement depuis /platform-v4. Les fonctions
déjà solides (giveaways, événements, backups, rôles, économie) sont réutilisées au lieu
d'être dupliquées.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import Counter, defaultdict
from typing import Any

import discord
from discord.ext import commands, tasks

from database.db import now
from utils.instance_identity import brand_label

logger = logging.getLogger("bot.platform-v4")

SCHEMA = """
CREATE TABLE IF NOT EXISTS platform_v4_settings (
    guild_id INTEGER PRIMARY KEY,
    currency_name TEXT NOT NULL DEFAULT 'pièces',
    currency_emoji TEXT NOT NULL DEFAULT '🪙',
    accent_color TEXT NOT NULL DEFAULT '#7d8cff',
    scheduled_announcements_enabled INTEGER NOT NULL DEFAULT 1,
    live_dashboard_enabled INTEGER NOT NULL DEFAULT 1,
    updated_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS scheduled_announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    run_at INTEGER NOT NULL,
    repeat_seconds INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER,
    created_at INTEGER NOT NULL,
    last_sent_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_scheduled_announcements_due ON scheduled_announcements (enabled, run_at);
CREATE TABLE IF NOT EXISTS platform_custom_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    response TEXT NOT NULL,
    embed_title TEXT NOT NULL DEFAULT '',
    embed_color INTEGER NOT NULL DEFAULT 8228095,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(guild_id, name)
);
CREATE TABLE IF NOT EXISTS platform_role_menus (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_by INTEGER,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_role_menu_items (
    menu_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (menu_id, role_id)
);
CREATE TABLE IF NOT EXISTS platform_market_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    seller_id INTEGER NOT NULL,
    item_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    buyer_id INTEGER,
    created_at INTEGER NOT NULL,
    sold_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_platform_market_guild_status ON platform_market_listings (guild_id, status, created_at DESC);
CREATE TABLE IF NOT EXISTS platform_trade_offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    creator_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    offer_item TEXT NOT NULL,
    offer_quantity INTEGER NOT NULL,
    want_item TEXT NOT NULL DEFAULT '',
    want_quantity INTEGER NOT NULL DEFAULT 0,
    want_money INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at INTEGER NOT NULL,
    resolved_at INTEGER
);
CREATE TABLE IF NOT EXISTS platform_item_catalog (
    guild_id INTEGER NOT NULL,
    item_name TEXT NOT NULL,
    effect_type TEXT NOT NULL DEFAULT 'money',
    effect_value INTEGER NOT NULL DEFAULT 0,
    role_id INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (guild_id, item_name)
);
CREATE TABLE IF NOT EXISTS platform_event_meta (
    event_id INTEGER PRIMARY KEY,
    reminder_minutes INTEGER NOT NULL DEFAULT 15,
    reminder_sent INTEGER NOT NULL DEFAULT 0,
    reward_amount INTEGER NOT NULL DEFAULT 0,
    reward_paid INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS platform_giveaway_rules (
    giveaway_id INTEGER PRIMARY KEY,
    min_account_age_days INTEGER NOT NULL DEFAULT 0,
    min_member_age_days INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS platform_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    actor_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL DEFAULT '',
    target_id TEXT NOT NULL DEFAULT '',
    old_json TEXT,
    new_json TEXT,
    rollback_kind TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_platform_audit_guild_time ON platform_audit_log (guild_id, created_at DESC);
"""

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")


def _loads(value: str | None, default: Any):
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError):
        return default


def _dict(row) -> dict[str, Any]:
    return dict(row) if row is not None else {}


async def _ensure_schema(bot: commands.Bot) -> None:
    for statement in SCHEMA.split(";"):
        sql = statement.strip()
        if sql:
            await bot.db.execute(sql)


class RoleToggleButton(discord.ui.Button):
    def __init__(self, service: "PlatformV4", menu_id: int, role_id: int, label: str, row: int):
        super().__init__(
            label=label[:80],
            style=discord.ButtonStyle.secondary,
            custom_id=f"pv4:role:{menu_id}:{role_id}",
            row=row,
        )
        self.service = service
        self.role_id = int(role_id)

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Ce bouton fonctionne uniquement sur un serveur.", ephemeral=True)
        role = interaction.guild.get_role(self.role_id)
        me = interaction.guild.me
        if role is None or role.managed or me is None or role >= me.top_role:
            return await interaction.response.send_message("Ce rôle n'est plus attribuable par le bot.", ephemeral=True)
        dangerous = role.permissions.administrator or role.permissions.manage_guild or role.permissions.manage_roles or role.permissions.ban_members or role.permissions.kick_members
        if dangerous:
            return await interaction.response.send_message("Ce rôle est trop sensible pour un menu public.", ephemeral=True)
        try:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role, reason=f"Menu de rôles {brand_label()}")
                text = f"Rôle **{role.name}** retiré."
            else:
                await interaction.user.add_roles(role, reason=f"Menu de rôles {brand_label()}")
                text = f"Rôle **{role.name}** ajouté."
            await interaction.response.send_message(text, ephemeral=True)
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message("Je n'ai pas la permission de modifier ce rôle.", ephemeral=True)


class RoleMenuView(discord.ui.View):
    def __init__(self, service: "PlatformV4", menu_id: int, items: list[dict[str, Any]]):
        super().__init__(timeout=None)
        for index, item in enumerate(items[:20]):
            self.add_item(RoleToggleButton(service, menu_id, int(item["role_id"]), str(item["label"]), index // 4))


class EventActionButton(discord.ui.Button):
    def __init__(self, service: "PlatformV4", event_id: int, action: str):
        label = "Participer" if action == "join" else "Se retirer"
        style = discord.ButtonStyle.primary if action == "join" else discord.ButtonStyle.secondary
        super().__init__(label=label, style=style, custom_id=f"pv4:event:{action}:{event_id}")
        self.service = service
        self.event_id = int(event_id)
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Serveur introuvable.", ephemeral=True)
        event = await self.service.bot.db.fetchone(
            "SELECT * FROM events WHERE id=? AND guild_id=? AND status NOT IN ('annule','termine')",
            (self.event_id, interaction.guild.id),
        )
        if not event:
            return await interaction.response.send_message("Cet événement n'est plus disponible.", ephemeral=True)
        if self.action == "join":
            await self.service.bot.db.execute(
                "INSERT OR IGNORE INTO event_participants (event_id,user_id) VALUES (?,?)",
                (self.event_id, interaction.user.id),
            )
            text = f"Tu participes maintenant à **{event['name']}**."
        else:
            await self.service.bot.db.execute(
                "DELETE FROM event_participants WHERE event_id=? AND user_id=?",
                (self.event_id, interaction.user.id),
            )
            text = f"Tu ne participes plus à **{event['name']}**."
        await interaction.response.send_message(text, ephemeral=True)


class EventSignupView(discord.ui.View):
    def __init__(self, service: "PlatformV4", event_id: int):
        super().__init__(timeout=None)
        self.add_item(EventActionButton(service, event_id, "join"))
        self.add_item(EventActionButton(service, event_id, "leave"))


class GiveawayEntryButton(discord.ui.Button):
    def __init__(self, service: "PlatformV4", giveaway_id: int):
        super().__init__(
            label="Participer",
            style=discord.ButtonStyle.primary,
            custom_id=f"pv4:giveaway:enter:{giveaway_id}",
        )
        self.service = service
        self.giveaway_id = int(giveaway_id)

    async def callback(self, interaction: discord.Interaction):
        await self.service.enter_giveaway(interaction, self.giveaway_id)


class PlatformGiveawayView(discord.ui.View):
    def __init__(self, service: "PlatformV4", giveaway_id: int):
        super().__init__(timeout=None)
        self.add_item(GiveawayEntryButton(service, giveaway_id))


class PlatformV4(commands.Cog):
    """Service sans nouvelles commandes publiques, consommé par le dashboard V4."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._money_lock = asyncio.Lock()
        self._ready_views = False

    async def cog_load(self):
        await _ensure_schema(self.bot)
        if not self.scheduler.is_running():
            self.scheduler.start()
        if not self.event_maintenance.is_running():
            self.event_maintenance.start()
        self._restore_task = asyncio.create_task(self._restore_persistent_views())

    async def cog_unload(self):
        self.scheduler.cancel()
        self.event_maintenance.cancel()
        task = getattr(self, "_restore_task", None)
        if task:
            task.cancel()

    async def _restore_persistent_views(self):
        await self.bot.wait_until_ready()
        if self._ready_views:
            return
        self._ready_views = True
        try:
            menus = await self.bot.db.fetchall("SELECT * FROM platform_role_menus WHERE message_id != 0")
            for menu in menus:
                items = [dict(r) for r in await self.bot.db.fetchall(
                    "SELECT * FROM platform_role_menu_items WHERE menu_id=? ORDER BY position ASC", (menu["id"],)
                )]
                if items:
                    self.bot.add_view(RoleMenuView(self, int(menu["id"]), items), message_id=int(menu["message_id"]))
            events = await self.bot.db.fetchall("SELECT id,message_id FROM events WHERE status IN ('planifie','en_cours') AND message_id IS NOT NULL")
            for event in events:
                if int(event["message_id"] or 0):
                    self.bot.add_view(EventSignupView(self, int(event["id"])), message_id=int(event["message_id"]))
            giveaways = await self.bot.db.fetchall(
                "SELECT g.id,g.message_id FROM giveaways g JOIN platform_giveaway_rules r ON r.giveaway_id=g.id WHERE g.status='actif'"
            )
            for giveaway in giveaways:
                self.bot.add_view(PlatformGiveawayView(self, int(giveaway["id"])), message_id=int(giveaway["message_id"]))
        except Exception:
            logger.exception("Restauration des vues Platform V4 impossible.")

    # ----------------------------------------------------------- settings / audit
    async def get_settings(self, guild_id: int) -> dict[str, Any]:
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO platform_v4_settings (guild_id,updated_at) VALUES (?,?)",
            (guild_id, now()),
        )
        return _dict(await self.bot.db.fetchone("SELECT * FROM platform_v4_settings WHERE guild_id=?", (guild_id,)))

    async def audit(self, guild_id: int, actor_id: int, action: str, *, target_type: str = "", target_id: Any = "", old: Any = None, new: Any = None, rollback_kind: str = "") -> int:
        cur = await self.bot.db.execute(
            "INSERT INTO platform_audit_log (guild_id,actor_id,action,target_type,target_id,old_json,new_json,rollback_kind,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                guild_id, actor_id, action[:120], target_type[:80], str(target_id)[:120],
                json.dumps(old, ensure_ascii=False, default=str) if old is not None else None,
                json.dumps(new, ensure_ascii=False, default=str) if new is not None else None,
                rollback_kind[:80], now(),
            ),
        )
        return int(cur.lastrowid)

    async def update_settings(self, guild: discord.Guild, actor_id: int, data: dict[str, Any]) -> dict[str, Any]:
        old = await self.get_settings(guild.id)
        clean = {
            "currency_name": str(data.get("currency_name", old.get("currency_name", "pièces"))).strip()[:32] or "pièces",
            "currency_emoji": str(data.get("currency_emoji", old.get("currency_emoji", "🪙"))).strip()[:16] or "🪙",
            "accent_color": str(data.get("accent_color", old.get("accent_color", "#7d8cff"))).strip()[:16],
            "scheduled_announcements_enabled": int(bool(data.get("scheduled_announcements_enabled", old.get("scheduled_announcements_enabled", 1)))),
            "live_dashboard_enabled": int(bool(data.get("live_dashboard_enabled", old.get("live_dashboard_enabled", 1)))),
        }
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", clean["accent_color"]):
            clean["accent_color"] = "#7d8cff"
        await self.bot.db.execute(
            "UPDATE platform_v4_settings SET currency_name=?,currency_emoji=?,accent_color=?,scheduled_announcements_enabled=?,live_dashboard_enabled=?,updated_at=? WHERE guild_id=?",
            (*clean.values(), now(), guild.id),
        )
        new = await self.get_settings(guild.id)
        await self.audit(guild.id, actor_id, "Réglages Platform V4 modifiés", target_type="settings", target_id=guild.id, old=old, new=new, rollback_kind="settings")
        return new

    async def list_audit(self, guild_id: int, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self.bot.db.fetchall(
            "SELECT * FROM platform_audit_log WHERE guild_id=? ORDER BY id DESC LIMIT ?", (guild_id, max(1, min(limit, 300)))
        )
        return [dict(r) for r in rows]

    async def rollback(self, guild: discord.Guild, actor_id: int, audit_id: int) -> dict[str, Any]:
        row = await self.bot.db.fetchone("SELECT * FROM platform_audit_log WHERE id=? AND guild_id=?", (audit_id, guild.id))
        if not row or not row["rollback_kind"]:
            raise ValueError("Cette action n'est pas restaurable automatiquement.")
        old = _loads(row["old_json"], None)
        kind = row["rollback_kind"]
        if kind == "settings" and isinstance(old, dict):
            await self.bot.db.execute(
                "UPDATE platform_v4_settings SET currency_name=?,currency_emoji=?,accent_color=?,scheduled_announcements_enabled=?,live_dashboard_enabled=?,updated_at=? WHERE guild_id=?",
                (
                    old.get("currency_name", "pièces"), old.get("currency_emoji", "🪙"), old.get("accent_color", "#7d8cff"),
                    int(old.get("scheduled_announcements_enabled", 1)), int(old.get("live_dashboard_enabled", 1)), now(), guild.id,
                ),
            )
        elif kind == "custom_command":
            target_id = int(row["target_id"] or 0)
            if old is None:
                await self.bot.db.execute("DELETE FROM platform_custom_commands WHERE id=? AND guild_id=?", (target_id, guild.id))
            else:
                await self.bot.db.execute(
                    "INSERT OR REPLACE INTO platform_custom_commands (id,guild_id,name,response,embed_title,embed_color,enabled,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        target_id, guild.id, old["name"], old["response"], old.get("embed_title", ""), int(old.get("embed_color", 8228095)),
                        int(old.get("enabled", 1)), old.get("created_by"), int(old.get("created_at", now())), now(),
                    ),
                )
        elif kind == "announcement":
            target_id = int(row["target_id"] or 0)
            if old is None:
                await self.bot.db.execute("DELETE FROM scheduled_announcements WHERE id=? AND guild_id=?", (target_id, guild.id))
            else:
                await self.bot.db.execute(
                    "INSERT OR REPLACE INTO scheduled_announcements (id,guild_id,channel_id,title,content,run_at,repeat_seconds,enabled,created_by,created_at,last_sent_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        target_id, guild.id, old["channel_id"], old.get("title", ""), old["content"], old["run_at"], old.get("repeat_seconds", 0),
                        old.get("enabled", 1), old.get("created_by"), old.get("created_at", now()), old.get("last_sent_at"),
                    ),
                )
        else:
            raise ValueError("Ce type de rollback n'est pas pris en charge.")
        await self.audit(guild.id, actor_id, f"Rollback audit #{audit_id}", target_type="rollback", target_id=audit_id, old=None, new={"source": audit_id})
        return {"ok": True, "kind": kind}

    # ----------------------------------------------------------- announcements
    async def list_announcements(self, guild_id: int) -> list[dict[str, Any]]:
        rows = await self.bot.db.fetchall("SELECT * FROM scheduled_announcements WHERE guild_id=? ORDER BY enabled DESC,run_at ASC", (guild_id,))
        return [dict(r) for r in rows]

    async def save_announcement(self, guild: discord.Guild, actor_id: int, data: dict[str, Any]) -> dict[str, Any]:
        channel_id = int(data.get("channel_id") or 0)
        if not isinstance(guild.get_channel(channel_id), discord.TextChannel):
            raise ValueError('Choisissez un salon textuel valide.')
        content = str(data.get("content") or "").strip()[:3900]
        title = str(data.get("title") or "").strip()[:200]
        if not content:
            raise ValueError("Le contenu de l'annonce est vide.")
        run_at = int(data.get("run_at") or 0)
        if run_at < now() - 60:
            raise ValueError("La date d'envoi est déjà passée.")
        repeat_seconds = max(0, min(int(data.get("repeat_seconds") or 0), 31_536_000))
        announcement_id = int(data.get("id") or 0)
        old = None
        if announcement_id:
            old_row = await self.bot.db.fetchone("SELECT * FROM scheduled_announcements WHERE id=? AND guild_id=?", (announcement_id, guild.id))
            if not old_row:
                raise ValueError("Annonce introuvable.")
            old = dict(old_row)
            await self.bot.db.execute(
                "UPDATE scheduled_announcements SET channel_id=?,title=?,content=?,run_at=?,repeat_seconds=?,enabled=1 WHERE id=? AND guild_id=?",
                (channel_id, title, content, run_at, repeat_seconds, announcement_id, guild.id),
            )
        else:
            cur = await self.bot.db.execute(
                "INSERT INTO scheduled_announcements (guild_id,channel_id,title,content,run_at,repeat_seconds,enabled,created_by,created_at) VALUES (?,?,?,?,?,?,1,?,?)",
                (guild.id, channel_id, title, content, run_at, repeat_seconds, actor_id, now()),
            )
            announcement_id = int(cur.lastrowid)
        new = dict(await self.bot.db.fetchone("SELECT * FROM scheduled_announcements WHERE id=?", (announcement_id,)))
        await self.audit(guild.id, actor_id, "Annonce programmée enregistrée", target_type="announcement", target_id=announcement_id, old=old, new=new, rollback_kind="announcement")
        return new

    async def cancel_announcement(self, guild_id: int, actor_id: int, announcement_id: int):
        row = await self.bot.db.fetchone("SELECT * FROM scheduled_announcements WHERE id=? AND guild_id=?", (announcement_id, guild_id))
        if not row:
            raise ValueError("Annonce introuvable.")
        old = dict(row)
        await self.bot.db.execute("UPDATE scheduled_announcements SET enabled=0 WHERE id=?", (announcement_id,))
        new = dict(await self.bot.db.fetchone("SELECT * FROM scheduled_announcements WHERE id=?", (announcement_id,)))
        await self.audit(guild_id, actor_id, "Annonce programmée désactivée", target_type="announcement", target_id=announcement_id, old=old, new=new, rollback_kind="announcement")

    @tasks.loop(seconds=30)
    async def scheduler(self):
        rows = await self.bot.db.fetchall("SELECT * FROM scheduled_announcements WHERE enabled=1 AND run_at<=? ORDER BY run_at ASC LIMIT 30", (now(),))
        for row in rows:
            guild = self.bot.get_guild(row["guild_id"])
            channel = guild.get_channel(row["channel_id"]) if guild else None
            sent = False
            if isinstance(channel, discord.TextChannel):
                try:
                    if row["title"]:
                        embed = discord.Embed(title=row["title"], description=row["content"], color=0x7D8CFF)
                        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                    else:
                        await channel.send(row["content"], allowed_mentions=discord.AllowedMentions.none())
                    sent = True
                except discord.HTTPException:
                    logger.exception("Annonce programmée #%s non envoyée.", row["id"])
            if row["repeat_seconds"] and sent:
                next_run = max(now(), int(row["run_at"])) + int(row["repeat_seconds"])
                await self.bot.db.execute("UPDATE scheduled_announcements SET run_at=?,last_sent_at=? WHERE id=?", (next_run, now(), row["id"]))
            else:
                await self.bot.db.execute("UPDATE scheduled_announcements SET enabled=0,last_sent_at=? WHERE id=?", (now() if sent else None, row["id"]))

    @scheduler.before_loop
    async def before_scheduler(self):
        await self.bot.wait_until_ready()

    # ----------------------------------------------------------- custom commands
    async def list_custom_commands(self, guild_id: int) -> list[dict[str, Any]]:
        return [dict(r) for r in await self.bot.db.fetchall("SELECT * FROM platform_custom_commands WHERE guild_id=? ORDER BY name", (guild_id,))]

    async def save_custom_command(self, guild: discord.Guild, actor_id: int, data: dict[str, Any]) -> dict[str, Any]:
        name = str(data.get("name") or "").strip().lower().lstrip("+")
        if not _NAME_RE.fullmatch(name):
            raise ValueError("Nom invalide : 2 à 32 caractères, lettres/chiffres/_/- uniquement.")
        if self.bot.get_command(name):
            raise ValueError("Ce nom est déjà utilisé par une commande du bot.")
        response = str(data.get("response") or "").strip()[:1900]
        if not response:
            raise ValueError("La réponse ne peut pas être vide.")
        command_id = int(data.get("id") or 0)
        old = None
        if command_id:
            row = await self.bot.db.fetchone("SELECT * FROM platform_custom_commands WHERE id=? AND guild_id=?", (command_id, guild.id))
            if not row:
                raise ValueError("Commande introuvable.")
            old = dict(row)
            await self.bot.db.execute(
                "UPDATE platform_custom_commands SET name=?,response=?,embed_title=?,embed_color=?,enabled=?,updated_at=? WHERE id=? AND guild_id=?",
                (name, response, str(data.get("embed_title") or "")[:200], int(data.get("embed_color") or 8228095) & 0xFFFFFF, int(bool(data.get("enabled", True))), now(), command_id, guild.id),
            )
        else:
            cur = await self.bot.db.execute(
                "INSERT INTO platform_custom_commands (guild_id,name,response,embed_title,embed_color,enabled,created_by,created_at,updated_at) VALUES (?,?,?,?,?,1,?,?,?)",
                (guild.id, name, response, str(data.get("embed_title") or "")[:200], int(data.get("embed_color") or 8228095) & 0xFFFFFF, actor_id, now(), now()),
            )
            command_id = int(cur.lastrowid)
        new = dict(await self.bot.db.fetchone("SELECT * FROM platform_custom_commands WHERE id=?", (command_id,)))
        await self.audit(guild.id, actor_id, "Commande personnalisée enregistrée", target_type="custom_command", target_id=command_id, old=old, new=new, rollback_kind="custom_command")
        return new

    async def delete_custom_command(self, guild_id: int, actor_id: int, command_id: int):
        row = await self.bot.db.fetchone("SELECT * FROM platform_custom_commands WHERE id=? AND guild_id=?", (command_id, guild_id))
        if not row:
            raise ValueError("Commande introuvable.")
        old = dict(row)
        await self.bot.db.execute("DELETE FROM platform_custom_commands WHERE id=?", (command_id,))
        await self.audit(guild_id, actor_id, "Commande personnalisée supprimée", target_type="custom_command", target_id=command_id, old=old, new=None, rollback_kind="custom_command")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot or not message.content:
            return
        conf = await self.bot.db.get_guild_config(message.guild.id)
        prefix = str(conf["prefix"] if conf and conf["prefix"] else "+")
        if not message.content.startswith(prefix):
            return
        raw = message.content[len(prefix):].strip()
        if not raw:
            return
        name, _, args = raw.partition(" ")
        name = name.lower()
        if self.bot.get_command(name):
            return
        row = await self.bot.db.fetchone(
            "SELECT * FROM platform_custom_commands WHERE guild_id=? AND name=? AND enabled=1", (message.guild.id, name)
        )
        if not row:
            return
        response = str(row["response"] or "")
        response = response.replace("{user}", message.author.mention).replace("{server}", message.guild.name).replace("{args}", args[:1000])
        try:
            if row["embed_title"]:
                embed = discord.Embed(title=row["embed_title"], description=response, color=int(row["embed_color"] or 8228095))
                await message.channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
            else:
                await message.channel.send(response, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
        except discord.HTTPException:
            pass

    # ----------------------------------------------------------- role menus
    async def create_role_menu(self, guild: discord.Guild, actor_id: int, data: dict[str, Any]) -> dict[str, Any]:
        channel = guild.get_channel(int(data.get("channel_id") or 0))
        if not isinstance(channel, discord.TextChannel):
            raise ValueError('Choisissez un salon textuel valide.')
        raw_roles = data.get("roles") if isinstance(data.get("roles"), list) else []
        items = []
        me = guild.me
        for index, raw in enumerate(raw_roles[:20]):
            role_id = int(raw.get("role_id") if isinstance(raw, dict) else raw)
            role = guild.get_role(role_id)
            if role is None or role.managed or role.is_default() or me is None or role >= me.top_role:
                continue
            dangerous = role.permissions.administrator or role.permissions.manage_guild or role.permissions.manage_roles or role.permissions.ban_members or role.permissions.kick_members
            if dangerous:
                continue
            label = str(raw.get("label") if isinstance(raw, dict) else role.name).strip()[:80] or role.name[:80]
            items.append({"role_id": role.id, "label": label, "position": index})
        if not items:
            raise ValueError('Ajoutez au moins un rôle attribuable et non administratif.')
        title = str(data.get("title") or "Choisissez vos rôles").strip()[:200]
        description = str(data.get("description") or "Cliquez pour ajouter ou retirer un rôle.").strip()[:1500]
        cur = await self.bot.db.execute(
            "INSERT INTO platform_role_menus (guild_id,channel_id,title,description,created_by,created_at) VALUES (?,?,?,?,?,?)",
            (guild.id, channel.id, title, description, actor_id, now()),
        )
        menu_id = int(cur.lastrowid)
        for item in items:
            await self.bot.db.execute(
                "INSERT INTO platform_role_menu_items (menu_id,role_id,label,position) VALUES (?,?,?,?)",
                (menu_id, item["role_id"], item["label"], item["position"]),
            )
        view = RoleMenuView(self, menu_id, items)
        embed = discord.Embed(title=title, description=description, color=0x7D8CFF)
        message = await channel.send(embed=embed, view=view)
        await self.bot.db.execute("UPDATE platform_role_menus SET message_id=? WHERE id=?", (message.id, menu_id))
        self.bot.add_view(RoleMenuView(self, menu_id, items), message_id=message.id)
        await self.audit(guild.id, actor_id, "Menu de rôles publié", target_type="role_menu", target_id=menu_id, new={"channel_id": channel.id, "roles": items})
        return {"id": menu_id, "message_id": message.id, "channel_id": channel.id, "roles": items}

    # ----------------------------------------------------------- economy history / marketplace / usable items
    async def economy_history(self, guild_id: int, limit: int = 150) -> dict[str, Any]:
        rows = [dict(r) for r in await self.bot.db.fetchall(
            "SELECT * FROM economy_transactions WHERE guild_id=? ORDER BY created_at DESC LIMIT ?", (guild_id, max(1, min(limit, 500)))
        )]
        flagged = []
        actor_bursts: Counter[int] = Counter()
        cutoff = now() - 600
        for row in rows:
            amount = abs(int(row.get("amount") or 0))
            actor = int(row.get("sender_id") or row.get("receiver_id") or 0)
            if row.get("created_at", 0) >= cutoff and actor:
                actor_bursts[actor] += 1
            reasons = []
            if amount >= 100_000:
                reasons.append("montant élevé")
            if amount >= 1_000_000:
                reasons.append("montant exceptionnel")
            if reasons:
                flagged.append({"transaction_id": row.get("transaction_id"), "reasons": reasons, "amount": amount})
        for actor, count in actor_bursts.items():
            if count >= 12:
                flagged.append({"user_id": actor, "reasons": [f"{count} transactions en 10 min"], "amount": 0})
        return {"transactions": rows, "flags": flagged[:50]}

    async def list_market(self, guild_id: int) -> list[dict[str, Any]]:
        return [dict(r) for r in await self.bot.db.fetchall("SELECT * FROM platform_market_listings WHERE guild_id=? AND status='active' ORDER BY id DESC LIMIT 100", (guild_id,))]

    async def create_listing(self, guild_id: int, seller_id: int, item_name: str, quantity: int, unit_price: int) -> dict[str, Any]:
        item_name = item_name.strip()[:100]
        quantity = max(1, min(int(quantity), 9999))
        unit_price = max(1, min(int(unit_price), 2_000_000_000))
        async with self._money_lock:
            row = await self.bot.db.fetchone("SELECT quantity FROM inventory WHERE guild_id=? AND user_id=? AND item_name=?", (guild_id, seller_id, item_name))
            if not row or int(row["quantity"]) < quantity:
                raise ValueError("Vous n'avez pas assez de cet objet dans votre inventaire.")
            left = int(row["quantity"]) - quantity
            if left:
                await self.bot.db.execute("UPDATE inventory SET quantity=? WHERE guild_id=? AND user_id=? AND item_name=?", (left, guild_id, seller_id, item_name))
            else:
                await self.bot.db.execute("DELETE FROM inventory WHERE guild_id=? AND user_id=? AND item_name=?", (guild_id, seller_id, item_name))
            cur = await self.bot.db.execute(
                "INSERT INTO platform_market_listings (guild_id,seller_id,item_name,quantity,unit_price,status,created_at) VALUES (?,?,?,?,?,'active',?)",
                (guild_id, seller_id, item_name, quantity, unit_price, now()),
            )
        return dict(await self.bot.db.fetchone("SELECT * FROM platform_market_listings WHERE id=?", (cur.lastrowid,)))

    async def buy_listing(self, guild_id: int, buyer_id: int, listing_id: int) -> dict[str, Any]:
        async with self._money_lock:
            listing = await self.bot.db.fetchone("SELECT * FROM platform_market_listings WHERE id=? AND guild_id=? AND status='active'", (listing_id, guild_id))
            if not listing:
                raise ValueError("Cette annonce n'est plus disponible.")
            if int(listing["seller_id"]) == buyer_id:
                raise ValueError('Vous ne pouvez pas acheter votre propre annonce.')
            total = int(listing["quantity"]) * int(listing["unit_price"])
            await self.bot.db.ensure_economy(guild_id, buyer_id)
            balance = await self.bot.db.get_balance(guild_id, buyer_id)
            if int(balance["cash"]) < total:
                raise ValueError("Solde insuffisant dans le portefeuille.")
            await self.bot.db.add_balance(guild_id, buyer_id, -total)
            await self.bot.db.add_balance(guild_id, int(listing["seller_id"]), total)
            await self.bot.db.execute(
                "INSERT INTO inventory (guild_id,user_id,item_name,quantity) VALUES (?,?,?,?) ON CONFLICT(guild_id,user_id,item_name) DO UPDATE SET quantity=quantity+excluded.quantity",
                (guild_id, buyer_id, listing["item_name"], int(listing["quantity"])),
            )
            await self.bot.db.execute("UPDATE platform_market_listings SET status='sold',buyer_id=?,sold_at=? WHERE id=?", (buyer_id, now(), listing_id))
            await self.bot.db.log_transaction(guild_id, buyer_id, int(listing["seller_id"]), "marketplace", total, f"Achat #{listing_id}: {listing['item_name']}")
        return {"listing_id": listing_id, "total": total, "item_name": listing["item_name"], "quantity": int(listing["quantity"])}

    async def cancel_listing(self, guild_id: int, user_id: int, listing_id: int, *, admin: bool = False):
        async with self._money_lock:
            listing = await self.bot.db.fetchone("SELECT * FROM platform_market_listings WHERE id=? AND guild_id=? AND status='active'", (listing_id, guild_id))
            if not listing:
                raise ValueError("Annonce introuvable.")
            if not admin and int(listing["seller_id"]) != user_id:
                raise ValueError("Vous ne pouvez pas annuler l'annonce d'un autre membre.")
            await self.bot.db.execute(
                "INSERT INTO inventory (guild_id,user_id,item_name,quantity) VALUES (?,?,?,?) ON CONFLICT(guild_id,user_id,item_name) DO UPDATE SET quantity=quantity+excluded.quantity",
                (guild_id, int(listing["seller_id"]), listing["item_name"], int(listing["quantity"])),
            )
            await self.bot.db.execute("UPDATE platform_market_listings SET status='cancelled' WHERE id=?", (listing_id,))

    async def create_trade(self, guild_id: int, creator_id: int, target_id: int, offer_item: str, offer_quantity: int, want_item: str, want_quantity: int, want_money: int) -> dict[str, Any]:
        if creator_id == target_id:
            raise ValueError('Choisissez un autre membre.')
        offer_item = offer_item.strip()[:100]
        want_item = want_item.strip()[:100]
        offer_quantity = max(1, min(int(offer_quantity), 9999))
        want_quantity = max(0, min(int(want_quantity), 9999))
        want_money = max(0, min(int(want_money), 2_000_000_000))
        async with self._money_lock:
            row = await self.bot.db.fetchone("SELECT quantity FROM inventory WHERE guild_id=? AND user_id=? AND item_name=?", (guild_id, creator_id, offer_item))
            if not row or int(row["quantity"]) < offer_quantity:
                raise ValueError("Objet proposé insuffisant.")
            left = int(row["quantity"]) - offer_quantity
            if left:
                await self.bot.db.execute("UPDATE inventory SET quantity=? WHERE guild_id=? AND user_id=? AND item_name=?", (left, guild_id, creator_id, offer_item))
            else:
                await self.bot.db.execute("DELETE FROM inventory WHERE guild_id=? AND user_id=? AND item_name=?", (guild_id, creator_id, offer_item))
            cur = await self.bot.db.execute(
                "INSERT INTO platform_trade_offers (guild_id,creator_id,target_id,offer_item,offer_quantity,want_item,want_quantity,want_money,status,created_at) VALUES (?,?,?,?,?,?,?,?, 'pending',?)",
                (guild_id, creator_id, target_id, offer_item, offer_quantity, want_item, want_quantity, want_money, now()),
            )
        return dict(await self.bot.db.fetchone("SELECT * FROM platform_trade_offers WHERE id=?", (cur.lastrowid,)))

    async def accept_trade(self, guild_id: int, target_id: int, trade_id: int) -> dict[str, Any]:
        async with self._money_lock:
            trade = await self.bot.db.fetchone("SELECT * FROM platform_trade_offers WHERE id=? AND guild_id=? AND status='pending'", (trade_id, guild_id))
            if not trade or int(trade["target_id"]) != target_id:
                raise ValueError("Échange introuvable ou non destiné à ce membre.")
            if trade["want_item"] and int(trade["want_quantity"]):
                row = await self.bot.db.fetchone("SELECT quantity FROM inventory WHERE guild_id=? AND user_id=? AND item_name=?", (guild_id, target_id, trade["want_item"]))
                if not row or int(row["quantity"]) < int(trade["want_quantity"]):
                    raise ValueError("Vous n'avez pas les objets demandés.")
            if int(trade["want_money"]):
                await self.bot.db.ensure_economy(guild_id, target_id)
                bal = await self.bot.db.get_balance(guild_id, target_id)
                if int(bal["cash"]) < int(trade["want_money"]):
                    raise ValueError("Vous n'avez pas assez d'argent liquide.")
            if trade["want_item"] and int(trade["want_quantity"]):
                qty = int(trade["want_quantity"])
                await self.bot.db.execute("UPDATE inventory SET quantity=quantity-? WHERE guild_id=? AND user_id=? AND item_name=?", (qty, guild_id, target_id, trade["want_item"]))
                await self.bot.db.execute("DELETE FROM inventory WHERE guild_id=? AND user_id=? AND item_name=? AND quantity<=0", (guild_id, target_id, trade["want_item"]))
                await self.bot.db.execute("INSERT INTO inventory (guild_id,user_id,item_name,quantity) VALUES (?,?,?,?) ON CONFLICT(guild_id,user_id,item_name) DO UPDATE SET quantity=quantity+excluded.quantity", (guild_id, int(trade["creator_id"]), trade["want_item"], qty))
            if int(trade["want_money"]):
                amount = int(trade["want_money"])
                await self.bot.db.add_balance(guild_id, target_id, -amount)
                await self.bot.db.add_balance(guild_id, int(trade["creator_id"]), amount)
                await self.bot.db.log_transaction(guild_id, target_id, int(trade["creator_id"]), "trade", amount, f"Échange #{trade_id}")
            await self.bot.db.execute("INSERT INTO inventory (guild_id,user_id,item_name,quantity) VALUES (?,?,?,?) ON CONFLICT(guild_id,user_id,item_name) DO UPDATE SET quantity=quantity+excluded.quantity", (guild_id, target_id, trade["offer_item"], int(trade["offer_quantity"])))
            await self.bot.db.execute("UPDATE platform_trade_offers SET status='accepted',resolved_at=? WHERE id=?", (now(), trade_id))
        return dict(trade)

    async def configure_consumable(self, guild: discord.Guild, actor_id: int, data: dict[str, Any]) -> dict[str, Any]:
        item = str(data.get("item_name") or "").strip()[:100]
        effect = str(data.get("effect_type") or "money")
        if not item or effect not in {"money", "engagement_points", "role"}:
            raise ValueError("Objet ou effet invalide.")
        value = max(0, min(int(data.get("effect_value") or 0), 2_000_000_000))
        role_id = int(data.get("role_id") or 0) or None
        if effect == "role":
            role = guild.get_role(role_id or 0)
            me = guild.me
            if role is None or role.managed or me is None or role >= me.top_role or role.permissions.administrator or role.permissions.manage_guild or role.permissions.manage_roles:
                raise ValueError("Le rôle choisi n'est pas sûr ou attribuable.")
        await self.bot.db.execute(
            "INSERT INTO platform_item_catalog (guild_id,item_name,effect_type,effect_value,role_id,enabled) VALUES (?,?,?,?,?,1) ON CONFLICT(guild_id,item_name) DO UPDATE SET effect_type=excluded.effect_type,effect_value=excluded.effect_value,role_id=excluded.role_id,enabled=1",
            (guild.id, item, effect, value, role_id),
        )
        await self.audit(guild.id, actor_id, "Objet utilisable configuré", target_type="item", target_id=item, new={"effect": effect, "value": value, "role_id": role_id})
        return {"item_name": item, "effect_type": effect, "effect_value": value, "role_id": role_id}

    async def use_item(self, guild: discord.Guild, member: discord.Member, item_name: str) -> dict[str, Any]:
        async with self._money_lock:
            catalog = await self.bot.db.fetchone("SELECT * FROM platform_item_catalog WHERE guild_id=? AND item_name=? AND enabled=1", (guild.id, item_name))
            inv = await self.bot.db.fetchone("SELECT quantity FROM inventory WHERE guild_id=? AND user_id=? AND item_name=?", (guild.id, member.id, item_name))
            if not catalog or not inv or int(inv["quantity"]) <= 0:
                raise ValueError("Cet objet n'est pas utilisable ou absent de votre inventaire.")
            if catalog["effect_type"] == "role":
                role = guild.get_role(int(catalog["role_id"] or 0))
                me = guild.me
                if role is None or me is None or role >= me.top_role:
                    raise ValueError("Le rôle lié à cet objet n'est plus attribuable.")
                await member.add_roles(role, reason=f"Objet utilisable {brand_label()}")
            elif catalog["effect_type"] == "money":
                await self.bot.db.add_balance(guild.id, member.id, int(catalog["effect_value"]))
                await self.bot.db.log_transaction(guild.id, None, member.id, "item_use", int(catalog["effect_value"]), f"Objet {item_name}")
            elif catalog["effect_type"] == "engagement_points":
                await self.bot.db.execute("INSERT OR IGNORE INTO engagement_members (guild_id,user_id,last_seen_at) VALUES (?,?,?)", (guild.id, member.id, now()))
                await self.bot.db.execute("UPDATE engagement_members SET points=points+?,last_seen_at=? WHERE guild_id=? AND user_id=?", (int(catalog["effect_value"]), now(), guild.id, member.id))
            await self.bot.db.execute("UPDATE inventory SET quantity=quantity-1 WHERE guild_id=? AND user_id=? AND item_name=?", (guild.id, member.id, item_name))
            await self.bot.db.execute("DELETE FROM inventory WHERE guild_id=? AND user_id=? AND item_name=? AND quantity<=0", (guild.id, member.id, item_name))
        return {"item_name": item_name, "effect_type": catalog["effect_type"], "effect_value": int(catalog["effect_value"])}

    async def economy_achievements(self, guild_id: int, user_id: int) -> list[dict[str, Any]]:
        tx = await self.bot.db.fetchone("SELECT COUNT(*) c,COALESCE(SUM(ABS(amount)),0) total FROM economy_transactions WHERE guild_id=? AND (sender_id=? OR receiver_id=?)", (guild_id, user_id, user_id))
        inv = await self.bot.db.fetchone("SELECT COALESCE(SUM(quantity),0) q FROM inventory WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        listings = await self.bot.db.fetchone("SELECT COUNT(*) c FROM platform_market_listings WHERE guild_id=? AND seller_id=? AND status='sold'", (guild_id, user_id))
        values = {"transactions": int(tx["c"] if tx else 0), "volume": int(tx["total"] if tx else 0), "items": int(inv["q"] if inv else 0), "sales": int(listings["c"] if listings else 0)}
        checks = [
            ("Première transaction", values["transactions"] >= 1),
            ("Marchand — 5 ventes", values["sales"] >= 5),
            ("Collectionneur — 25 objets", values["items"] >= 25),
            ("Économie active — 100 000 de volume", values["volume"] >= 100_000),
        ]
        return [{"name": name, "unlocked": ok} for name, ok in checks]

    # ----------------------------------------------------------- events / giveaways V2
    async def create_event(self, guild: discord.Guild, actor_id: int, data: dict[str, Any]) -> dict[str, Any]:
        channel = guild.get_channel(int(data.get("channel_id") or 0))
        if not isinstance(channel, discord.TextChannel):
            raise ValueError('Choisissez un salon textuel valide.')
        name = str(data.get("name") or "Événement").strip()[:120]
        description = str(data.get("description") or "").strip()[:1500]
        start_at = int(data.get("start_at") or 0)
        if start_at <= now():
            raise ValueError("La date de début doit être dans le futur.")
        cur = await self.bot.db.execute(
            "INSERT INTO events (guild_id,channel_id,message_id,name,description,start_at,status,created_by,created_at) VALUES (?,?,?,?,?,?,'planifie',?,?)",
            (guild.id, channel.id, 0, name, description, start_at, actor_id, now()),
        )
        event_id = int(cur.lastrowid)
        reward = max(0, min(int(data.get("reward_amount") or 0), 10_000_000))
        reminder = max(1, min(int(data.get("reminder_minutes") or 15), 1440))
        await self.bot.db.execute("INSERT OR REPLACE INTO platform_event_meta (event_id,reminder_minutes,reward_amount) VALUES (?,?,?)", (event_id, reminder, reward))
        embed = discord.Embed(title=f"Événement — {name}", description=description or 'Inscris-vous avec le bouton ci-dessous.', color=0x7D8CFF)
        embed.add_field(name="Début", value=f"<t:{start_at}:F>\n<t:{start_at}:R>", inline=True)
        embed.add_field(name="Récompense", value=f"{reward:,} pièces".replace(",", " ") if reward else "Aucune", inline=True)
        view = EventSignupView(self, event_id)
        message = await channel.send(embed=embed, view=view)
        await self.bot.db.execute("UPDATE events SET message_id=? WHERE id=?", (message.id, event_id))
        self.bot.add_view(EventSignupView(self, event_id), message_id=message.id)
        await self.audit(guild.id, actor_id, "Événement dashboard créé", target_type="event", target_id=event_id, new={"name": name, "start_at": start_at, "reward": reward})
        return {"id": event_id, "message_id": message.id, "name": name, "start_at": start_at}

    async def create_giveaway(self, guild: discord.Guild, actor_id: int, data: dict[str, Any]) -> dict[str, Any]:
        channel = guild.get_channel(int(data.get("channel_id") or 0))
        if not isinstance(channel, discord.TextChannel):
            raise ValueError('Choisissez un salon textuel valide.')
        prize = str(data.get("prize") or "Prix").strip()[:300]
        end_at = int(data.get("end_at") or 0)
        if end_at <= now():
            raise ValueError("La fin du giveaway doit être dans le futur.")
        winners = max(1, min(int(data.get("winners_count") or 1), 20))
        required_role_id = int(data.get("required_role_id") or 0) or None
        excluded_role_id = int(data.get("excluded_role_id") or 0) or None
        bonus_role_id = int(data.get("bonus_role_id") or 0) or None
        required_level = max(0, min(int(data.get("required_level") or 0), 10000)) or None
        bonus_entries = max(1, min(int(data.get("bonus_entries") or 2), 20))
        cur = await self.bot.db.execute(
            "INSERT INTO giveaways (guild_id,channel_id,message_id,prize,winners_count,status,end_at,required_role_id,required_level,excluded_role_id,bonus_role_id,bonus_entries,created_by,created_at) VALUES (?,?,0,?,?,'actif',?,?,?,?,?,?,?,?)",
            (guild.id, channel.id, prize, winners, end_at, required_role_id, required_level, excluded_role_id, bonus_role_id, bonus_entries, actor_id, now()),
        )
        giveaway_id = int(cur.lastrowid)
        min_account = max(0, min(int(data.get("min_account_age_days") or 0), 3650))
        min_member = max(0, min(int(data.get("min_member_age_days") or 0), 3650))
        await self.bot.db.execute("INSERT INTO platform_giveaway_rules (giveaway_id,min_account_age_days,min_member_age_days) VALUES (?,?,?)", (giveaway_id, min_account, min_member))
        embed = discord.Embed(title="GIVEAWAY", description=f'**Prix :** {prize}\n\nCliquez sur **Participer**.', color=0x7D8CFF)
        embed.add_field(name="Fin", value=f"<t:{end_at}:R>", inline=True)
        embed.add_field(name="Gagnants", value=str(winners), inline=True)
        if min_account:
            embed.add_field(name="Âge minimum du compte", value=f"{min_account} jour(s)", inline=True)
        if min_member:
            embed.add_field(name="Ancienneté serveur", value=f"{min_member} jour(s)", inline=True)
        view = PlatformGiveawayView(self, giveaway_id)
        message = await channel.send(embed=embed, view=view)
        await self.bot.db.execute("UPDATE giveaways SET message_id=? WHERE id=?", (message.id, giveaway_id))
        self.bot.add_view(PlatformGiveawayView(self, giveaway_id), message_id=message.id)
        await self.audit(guild.id, actor_id, "Giveaway V2 créé", target_type="giveaway", target_id=giveaway_id, new={"prize": prize, "end_at": end_at, "min_account": min_account, "min_member": min_member})
        return {"id": giveaway_id, "message_id": message.id, "prize": prize, "end_at": end_at}

    async def enter_giveaway(self, interaction: discord.Interaction, giveaway_id: int):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Participation impossible ici.", ephemeral=True)
        g = await self.bot.db.fetchone("SELECT * FROM giveaways WHERE id=? AND guild_id=? AND status='actif'", (giveaway_id, interaction.guild.id))
        if not g:
            return await interaction.response.send_message("Ce giveaway est terminé.", ephemeral=True)
        member = interaction.user
        blacklisted = await self.bot.db.fetchone("SELECT 1 FROM giveaway_blacklist WHERE guild_id=? AND user_id=?", (interaction.guild.id, member.id))
        if blacklisted:
            return await interaction.response.send_message("Vous n'êtes pas autorisé à participer aux giveaways.", ephemeral=True)
        if g["required_role_id"] and not any(r.id == g["required_role_id"] for r in member.roles):
            return await interaction.response.send_message("Il vous manque le rôle requis.", ephemeral=True)
        if g["excluded_role_id"] and any(r.id == g["excluded_role_id"] for r in member.roles):
            return await interaction.response.send_message('Un de vos rôles est exclu de ce giveaway.', ephemeral=True)
        if g["required_level"]:
            level = await self.bot.db.get_level(interaction.guild.id, member.id)
            if int(level["level"]) < int(g["required_level"]):
                return await interaction.response.send_message(f"Niveau {g['required_level']} minimum requis.", ephemeral=True)
        rule = await self.bot.db.fetchone("SELECT * FROM platform_giveaway_rules WHERE giveaway_id=?", (giveaway_id,))
        if rule:
            current = discord.utils.utcnow()
            account_days = (current - member.created_at).days
            joined_days = (current - member.joined_at).days if member.joined_at else 0
            if account_days < int(rule["min_account_age_days"]):
                return await interaction.response.send_message(f"Votre compte doit avoir au moins {rule['min_account_age_days']} jour(s).", ephemeral=True)
            if joined_days < int(rule["min_member_age_days"]):
                return await interaction.response.send_message(f"Vous devez être sur le serveur depuis au moins {rule['min_member_age_days']} jour(s).", ephemeral=True)
        existing = await self.bot.db.fetchone("SELECT 1 FROM giveaway_entries WHERE giveaway_id=? AND user_id=?", (giveaway_id, member.id))
        if existing:
            await self.bot.db.execute("DELETE FROM giveaway_entries WHERE giveaway_id=? AND user_id=?", (giveaway_id, member.id))
            return await interaction.response.send_message("Participation retirée.", ephemeral=True)
        await self.bot.db.execute("INSERT INTO giveaway_entries (giveaway_id,user_id) VALUES (?,?)", (giveaway_id, member.id))
        await interaction.response.send_message("Participation enregistrée.", ephemeral=True)

    @tasks.loop(minutes=1)
    async def event_maintenance(self):
        ts = now()
        rows = await self.bot.db.fetchall(
            "SELECT e.*,m.reminder_minutes,m.reminder_sent,m.reward_amount,m.reward_paid FROM events e JOIN platform_event_meta m ON m.event_id=e.id WHERE e.status IN ('planifie','en_cours')"
        )
        for row in rows:
            guild = self.bot.get_guild(row["guild_id"])
            channel = guild.get_channel(row["channel_id"]) if guild else None
            if not guild or not isinstance(channel, discord.TextChannel):
                continue
            remind_at = int(row["start_at"]) - int(row["reminder_minutes"]) * 60
            if row["status"] == "planifie" and not int(row["reminder_sent"]) and remind_at <= ts < int(row["start_at"]):
                participants = await self.bot.db.fetchall("SELECT user_id FROM event_participants WHERE event_id=? LIMIT 50", (row["id"],))
                mentions = " ".join(f"<@{p['user_id']}>" for p in participants)
                try:
                    await channel.send(f"Rappel : **{row['name']}** commence <t:{row['start_at']}:R>. {mentions}".strip(), allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
                    await self.bot.db.execute("UPDATE platform_event_meta SET reminder_sent=1 WHERE event_id=?", (row["id"],))
                except discord.HTTPException:
                    pass
            if row["status"] == "en_cours" and int(row["reward_amount"] or 0) > 0 and not int(row["reward_paid"]):
                participants = await self.bot.db.fetchall("SELECT user_id FROM event_participants WHERE event_id=?", (row["id"],))
                for participant in participants:
                    await self.bot.db.add_balance(guild.id, int(participant["user_id"]), int(row["reward_amount"]))
                    await self.bot.db.log_transaction(guild.id, None, int(participant["user_id"]), "event_reward", int(row["reward_amount"]), f"Événement {row['name']}")
                await self.bot.db.execute("UPDATE platform_event_meta SET reward_paid=1 WHERE event_id=?", (row["id"],))

    @event_maintenance.before_loop
    async def before_event_maintenance(self):
        await self.bot.wait_until_ready()

    # ----------------------------------------------------------- one-click setup / backups / health
    async def quick_setup(self, guild: discord.Guild, actor_id: int, profile: str = "community") -> dict[str, Any]:
        if profile not in {"community", "gaming", "support", "creator"}:
            profile = "community"
        me = guild.me
        if me is None or not me.guild_permissions.manage_channels:
            raise ValueError("Le bot a besoin de la permission Gérer les salons pour l'assistant 1 clic.")
        category = discord.utils.get(guild.categories, name="BOT & COMMUNAUTÉ")
        if category is None:
            category = await guild.create_category("BOT & COMMUNAUTÉ", reason=f"Configuration 1 clic {brand_label()}")
        wanted = {
            "bienvenue": "welcome_channel",
            "logs-bot": "log_channel",
            "tickets": "ticket_log_channel",
            "suggestions": "suggest_channel",
            "annonces": "announce_channel",
        }
        created = []
        channels = {}
        for name, field in wanted.items():
            channel = discord.utils.get(guild.text_channels, name=name)
            if channel is None:
                channel = await guild.create_text_channel(name, category=category, reason=f"Configuration 1 clic {brand_label()}")
                created.append(channel.name)
            channels[field] = channel.id
            await self.bot.db.set_guild_config(guild.id, field, channel.id)
        if me.guild_permissions.manage_roles:
            member_role = discord.utils.get(guild.roles, name="Membre")
            if member_role is None:
                member_role = await guild.create_role(name="Membre", reason=f"Configuration 1 clic {brand_label()}")
            await self.bot.db.set_guild_config(guild.id, "member_role", member_role.id)
        try:
            from .security_runtime_hardening import apply_recommended_security
            security = await apply_recommended_security(self.bot, guild)
        except Exception:
            security = {"missing_permissions": []}
        await self.bot.db.execute("INSERT OR IGNORE INTO engagement_settings (guild_id,updated_at) VALUES (?,?)", (guild.id, now()))
        await self.bot.db.execute("UPDATE engagement_settings SET profiles_enabled=1,quests_enabled=1,suggestions_enabled=1,suggestions_channel_id=?,updated_at=? WHERE guild_id=?", (channels["suggest_channel"], now(), guild.id))
        await self.bot.db.execute("INSERT OR IGNORE INTO community_growth_settings (guild_id,updated_at) VALUES (?,?)", (guild.id, now()))
        await self.audit(guild.id, actor_id, "Configuration 1 clic appliquée", target_type="setup", target_id=profile, new={"profile": profile, "created_channels": created, "channels": channels})
        return {"profile": profile, "created_channels": created, "channels": channels, "missing_permissions": security.get("missing_permissions", [])}

    def _snapshot_overwrites(self, channel) -> list[dict[str, Any]]:
        result = []
        for target, overwrite in channel.overwrites.items():
            allow, deny = overwrite.pair()
            result.append({"type": "role" if isinstance(target, discord.Role) else "member", "name": target.name if isinstance(target, discord.Role) else str(target.id), "allow": allow.value, "deny": deny.value})
        return result

    async def create_backup(self, guild: discord.Guild, actor_id: int, label: str) -> dict[str, Any]:
        label = label.strip()[:100] or f"Dashboard {time.strftime('%d/%m/%Y')}"
        data = {"roles": [], "categories": [], "uncategorized": []}
        for role in guild.roles:
            if role.is_default() or role.managed:
                continue
            data["roles"].append({"name": role.name, "color": role.color.value, "hoist": role.hoist, "mentionable": role.mentionable, "permissions": role.permissions.value, "position": role.position})
        for category in guild.categories:
            cat = {"name": category.name, "position": category.position, "overwrites": self._snapshot_overwrites(category), "channels": []}
            for channel in category.channels:
                if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                    continue
                item = {"name": channel.name, "type": "voice" if isinstance(channel, discord.VoiceChannel) else "text", "position": channel.position, "overwrites": self._snapshot_overwrites(channel)}
                if isinstance(channel, discord.TextChannel):
                    item.update({"topic": channel.topic, "nsfw": channel.nsfw, "slowmode_delay": channel.slowmode_delay})
                cat["channels"].append(item)
            data["categories"].append(cat)
        for channel in guild.channels:
            if channel.category is None and isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                data["uncategorized"].append({"name": channel.name, "type": "voice" if isinstance(channel, discord.VoiceChannel) else "text", "position": channel.position})
        cur = await self.bot.db.execute("INSERT INTO server_backups (guild_id,label,data_json,created_by,created_at) VALUES (?,?,?,?,?)", (guild.id, label, json.dumps(data), actor_id, now()))
        await self.audit(guild.id, actor_id, "Sauvegarde serveur créée", target_type="backup", target_id=cur.lastrowid, new={"label": label})
        return {"id": int(cur.lastrowid), "label": label, "roles": len(data["roles"]), "categories": len(data["categories"]), "channels": sum(len(c["channels"]) for c in data["categories"]) + len(data["uncategorized"])}

    async def list_backups(self, guild_id: int) -> list[dict[str, Any]]:
        return [dict(r) for r in await self.bot.db.fetchall("SELECT id,guild_id,label,created_by,created_at FROM server_backups WHERE guild_id=? ORDER BY id DESC LIMIT 50", (guild_id,))]

    async def restore_backup(self, guild: discord.Guild, actor_id: int, backup_id: int) -> dict[str, Any]:
        row = await self.bot.db.fetchone("SELECT * FROM server_backups WHERE id=? AND guild_id=?", (backup_id, guild.id))
        if not row:
            raise ValueError("Sauvegarde introuvable.")
        data = _loads(row["data_json"], {})
        created_roles = created_categories = created_channels = 0
        for role_data in sorted(data.get("roles", []), key=lambda x: x.get("position", 0)):
            if discord.utils.get(guild.roles, name=role_data.get("name")):
                continue
            await guild.create_role(name=role_data["name"], color=discord.Color(int(role_data.get("color", 0))), hoist=bool(role_data.get("hoist")), mentionable=bool(role_data.get("mentionable")), permissions=discord.Permissions(int(role_data.get("permissions", 0))), reason=f"Restauration dashboard #{backup_id}")
            created_roles += 1
        for cat_data in data.get("categories", []):
            category = discord.utils.get(guild.categories, name=cat_data.get("name"))
            if category is None:
                category = await guild.create_category(cat_data["name"], reason=f"Restauration dashboard #{backup_id}")
                created_categories += 1
            names = {c.name for c in category.channels}
            for ch in cat_data.get("channels", []):
                if ch.get("name") in names:
                    continue
                if ch.get("type") == "voice":
                    await guild.create_voice_channel(ch["name"], category=category, reason=f"Restauration dashboard #{backup_id}")
                else:
                    await guild.create_text_channel(ch["name"], category=category, topic=ch.get("topic"), nsfw=bool(ch.get("nsfw", False)), reason=f"Restauration dashboard #{backup_id}")
                created_channels += 1
        top = {c.name for c in guild.channels if c.category is None}
        for ch in data.get("uncategorized", []):
            if ch.get("name") in top:
                continue
            if ch.get("type") == "voice":
                await guild.create_voice_channel(ch["name"], reason=f"Restauration dashboard #{backup_id}")
            else:
                await guild.create_text_channel(ch["name"], reason=f"Restauration dashboard #{backup_id}")
            created_channels += 1
        result = {"created_roles": created_roles, "created_categories": created_categories, "created_channels": created_channels}
        await self.audit(guild.id, actor_id, "Sauvegarde serveur restaurée", target_type="backup_restore", target_id=backup_id, new=result)
        return result

    async def health(self, guild: discord.Guild) -> dict[str, Any]:
        start = time.perf_counter()
        db_ok = True
        try:
            await self.bot.db.fetchone("SELECT 1 AS ok")
        except Exception:
            db_ok = False
        db_ms = round((time.perf_counter() - start) * 1000, 1)
        open_tickets = await self.bot.db.fetchone("SELECT COUNT(*) c FROM tickets WHERE guild_id=? AND status='ouvert'", (guild.id,))
        pending_apps = await self.bot.db.fetchone("SELECT COUNT(*) c FROM staff_applications WHERE guild_id=? AND status='pending'", (guild.id,))
        return {
            "discord": bool(self.bot.is_ready()),
            "latency_ms": round(float(getattr(self.bot, "latency", 0.0)) * 1000, 1),
            "database": db_ok,
            "database_ms": db_ms,
            "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
            "redis_configured": bool(os.getenv("REDIS_URL")),
            "postgres_configured": bool(os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")),
            "guilds": len(getattr(self.bot, "guilds", [])),
            "members": int(guild.member_count or 0),
            "voice_connected": sum(len(c.members) for c in guild.voice_channels),
            "open_tickets": int(open_tickets["c"] if open_tickets else 0),
            "pending_applications": int(pending_apps["c"] if pending_apps else 0),
            "platform_v4": True,
        }

    async def live_stats(self, guild: discord.Guild) -> dict[str, Any]:
        messages = await self.bot.db.fetchone("SELECT COALESCE(SUM(count),0) c FROM message_counts WHERE guild_id=?", (guild.id,))
        active_giveaways = await self.bot.db.fetchone("SELECT COUNT(*) c FROM giveaways WHERE guild_id=? AND status='actif'", (guild.id,))
        events = await self.bot.db.fetchone("SELECT COUNT(*) c FROM events WHERE guild_id=? AND status IN ('planifie','en_cours')", (guild.id,))
        return {
            "members": int(guild.member_count or 0),
            "voice": sum(len(c.members) for c in guild.voice_channels),
            "messages_tracked": int(messages["c"] if messages else 0),
            "active_giveaways": int(active_giveaways["c"] if active_giveaways else 0),
            "active_events": int(events["c"] if events else 0),
            "latency_ms": round(float(getattr(self.bot, "latency", 0.0)) * 1000, 1),
            "timestamp": now(),
        }

    # ----------------------------------------------------------- staff analytics
    async def staff_stats(self, guild: discord.Guild) -> list[dict[str, Any]]:
        stats: dict[int, dict[str, Any]] = defaultdict(lambda: {"sanctions": 0, "tickets": 0, "ticket_seconds_total": 0, "applications": 0, "config_changes": 0})
        for row in await self.bot.db.fetchall("SELECT moderator_id,COUNT(*) c FROM sanctions WHERE guild_id=? GROUP BY moderator_id", (guild.id,)):
            if row["moderator_id"]:
                stats[int(row["moderator_id"])]["sanctions"] = int(row["c"])
        for row in await self.bot.db.fetchall("SELECT claimed_by,created_at,closed_at FROM tickets WHERE guild_id=? AND claimed_by IS NOT NULL", (guild.id,)):
            sid = int(row["claimed_by"])
            stats[sid]["tickets"] += 1
            if row["closed_at"] and row["created_at"] and int(row["closed_at"]) >= int(row["created_at"]):
                stats[sid]["ticket_seconds_total"] += int(row["closed_at"]) - int(row["created_at"])
        for row in await self.bot.db.fetchall("SELECT reviewer_id,COUNT(*) c FROM staff_applications WHERE guild_id=? AND reviewer_id IS NOT NULL GROUP BY reviewer_id", (guild.id,)):
            stats[int(row["reviewer_id"])]["applications"] = int(row["c"])
        for row in await self.bot.db.fetchall("SELECT user_id,COUNT(*) c FROM setup_history WHERE guild_id=? GROUP BY user_id", (guild.id,)):
            stats[int(row["user_id"])]["config_changes"] = int(row["c"])
        result = []
        for user_id, data in stats.items():
            member = guild.get_member(user_id)
            if not member:
                continue
            tickets = data["tickets"]
            result.append({
                "user_id": user_id,
                "name": member.display_name,
                "avatar_url": member.display_avatar.url,
                "sanctions": data["sanctions"],
                "tickets": tickets,
                "avg_ticket_minutes": round(data["ticket_seconds_total"] / max(1, tickets) / 60, 1) if tickets else 0,
                "applications": data["applications"],
                "config_changes": data["config_changes"],
            })
        return sorted(result, key=lambda x: x["name"].casefold())

    # ----------------------------------------------------------- privacy
    async def privacy_export(self, guild_id: int, user_id: int) -> dict[str, Any]:
        queries = {
            "economy": ("SELECT * FROM economy WHERE guild_id=? AND user_id=?", (guild_id, user_id)),
            "inventory": ("SELECT * FROM inventory WHERE guild_id=? AND user_id=?", (guild_id, user_id)),
            "levels": ("SELECT * FROM levels WHERE guild_id=? AND user_id=?", (guild_id, user_id)),
            "profile": ("SELECT * FROM profiles WHERE guild_id=? AND user_id=?", (guild_id, user_id)),
            "messages": ("SELECT * FROM message_counts WHERE guild_id=? AND user_id=?", (guild_id, user_id)),
            "voice": ("SELECT * FROM voice_totals WHERE guild_id=? AND user_id=?", (guild_id, user_id)),
            "engagement": ("SELECT * FROM engagement_members WHERE guild_id=? AND user_id=?", (guild_id, user_id)),
            "achievements": ("SELECT * FROM engagement_achievements WHERE guild_id=? AND user_id=?", (guild_id, user_id)),
            "quests": ("SELECT * FROM engagement_quest_progress WHERE guild_id=? AND user_id=?", (guild_id, user_id)),
            "economy_transactions": ("SELECT * FROM economy_transactions WHERE guild_id=? AND (sender_id=? OR receiver_id=?) ORDER BY created_at DESC LIMIT 500", (guild_id, user_id, user_id)),
            "ai_conversations": ("SELECT role,content,created_at FROM ai_conversations WHERE guild_id=? AND user_id=? ORDER BY created_at DESC LIMIT 200", (guild_id, user_id)),
            "applications": ("SELECT id,form_id,answers_json,status,created_at,updated_at FROM staff_applications WHERE guild_id=? AND user_id=? ORDER BY created_at DESC", (guild_id, user_id)),
        }
        data: dict[str, Any] = {"guild_id": guild_id, "user_id": user_id, "generated_at": now(), "retained_security_records": ["sanctions", "warnings", "setup/audit logs"]}
        for key, (sql, params) in queries.items():
            try:
                rows = await self.bot.db.fetchall(sql, params)
                data[key] = [dict(r) for r in rows]
            except Exception:
                data[key] = []
        return data

    async def privacy_delete(self, guild_id: int, user_id: int) -> dict[str, Any]:
        deletions = [
            ("economy", "DELETE FROM economy WHERE guild_id=? AND user_id=?"),
            ("inventory", "DELETE FROM inventory WHERE guild_id=? AND user_id=?"),
            ("levels", "DELETE FROM levels WHERE guild_id=? AND user_id=?"),
            ("profiles", "DELETE FROM profiles WHERE guild_id=? AND user_id=?"),
            ("message_counts", "DELETE FROM message_counts WHERE guild_id=? AND user_id=?"),
            ("voice_totals", "DELETE FROM voice_totals WHERE guild_id=? AND user_id=?"),
            ("engagement_members", "DELETE FROM engagement_members WHERE guild_id=? AND user_id=?"),
            ("engagement_achievements", "DELETE FROM engagement_achievements WHERE guild_id=? AND user_id=?"),
            ("engagement_quest_progress", "DELETE FROM engagement_quest_progress WHERE guild_id=? AND user_id=?"),
            ("engagement_season_scores", "DELETE FROM engagement_season_scores WHERE guild_id=? AND user_id=?"),
            ("ai_conversations", "DELETE FROM ai_conversations WHERE guild_id=? AND user_id=?"),
            ("ai_usage", "DELETE FROM ai_usage WHERE guild_id=? AND user_id=?"),
            ("platform_market_listings", "DELETE FROM platform_market_listings WHERE guild_id=? AND seller_id=? AND status!='active'"),
        ]
        removed = []
        async with self._money_lock:
            active = await self.bot.db.fetchone("SELECT COUNT(*) c FROM platform_market_listings WHERE guild_id=? AND seller_id=? AND status='active'", (guild_id, user_id))
            pending = await self.bot.db.fetchone("SELECT COUNT(*) c FROM platform_trade_offers WHERE guild_id=? AND (creator_id=? OR target_id=?) AND status='pending'", (guild_id, user_id, user_id))
            if (active and int(active["c"])) or (pending and int(pending["c"])):
                raise ValueError("Annulez d'abord vos ventes et échanges en cours avant de supprimer vos données économiques.")
            for name, sql in deletions:
                try:
                    cur = await self.bot.db.execute(sql, (guild_id, user_id))
                    if int(getattr(cur, "rowcount", 0) or 0) > 0:
                        removed.append(name)
                except Exception:
                    continue
            await self.bot.db.execute("UPDATE suggestions SET user_id=0 WHERE guild_id=? AND user_id=?", (guild_id, user_id))
            await self.bot.db.execute("UPDATE engagement_suggestions SET user_id=0 WHERE guild_id=? AND user_id=?", (guild_id, user_id))
            await self.bot.db.execute("UPDATE economy_transactions SET sender_id=CASE WHEN sender_id=? THEN 0 ELSE sender_id END, receiver_id=CASE WHEN receiver_id=? THEN 0 ELSE receiver_id END WHERE guild_id=? AND (sender_id=? OR receiver_id=?)", (user_id, user_id, guild_id, user_id, user_id))
        return {"deleted_categories": removed, "retained": ["sanctions/warnings", "security reviews", "audit logs", "anonymized economy ledger"]}


async def setup(bot: commands.Bot):
    await bot.add_cog(PlatformV4(bot))
