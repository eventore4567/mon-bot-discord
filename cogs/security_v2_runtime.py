"""SentriX Security V2 — protections anti-nuke, incidents et sauvegardes automatiques.

Cette couche complète les protections existantes sans remplacer les commandes historiques :
- seuil anti-nuke configurable par serveur et persistant SQLite ;
- rollback des rôles créés/supprimés/modifiés pendant une attaque ;
- restauration des changements de nom du serveur ;
- suppression des webhooks créés pendant une rafale lorsque Discord permet de les retrouver ;
- journal d'incidents anti-nuke persistant ;
- sauvegarde automatique de la structure des serveurs protégés, avec rétention limitée ;
- commandes de diagnostic simples, également exposées sous +security lorsque le centre V3 est chargé.

Aucune donnée réseau privée n'est collectée. Les snapshots ne contiennent que la structure
Discord nécessaire à la restauration (IDs, noms, permissions et positions).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from types import MethodType

import discord
from discord.ext import commands, tasks

from utils import embeds

logger = logging.getLogger("bot.security.v2")
_COG_NAME = "SecurityV2Runtime"
DEFAULT_WINDOW = 30
DEFAULT_THRESHOLD = 3
MIN_WINDOW = 5
MAX_WINDOW = 120
MIN_THRESHOLD = 2
MAX_THRESHOLD = 15
ROLLBACK_WINDOW = 60
AUTO_BACKUP_INTERVAL = 6 * 3600
AUTO_BACKUP_KEEP = 5


async def _ensure_tables(bot: commands.Bot) -> None:
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS antinuke_policy (
            guild_id INTEGER PRIMARY KEY,
            action_threshold INTEGER NOT NULL DEFAULT 3,
            window_seconds INTEGER NOT NULL DEFAULT 30,
            updated_by INTEGER,
            updated_at INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS security_incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            actor_id INTEGER,
            reason TEXT NOT NULL,
            summary_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL
        )
        """
    )
    await bot.db.execute(
        "CREATE INDEX IF NOT EXISTS idx_security_incidents_guild "
        "ON security_incidents (guild_id, created_at DESC)"
    )
    # Compatibilité si SecurityHardening n'a pas encore créé sa table au moment du patch.
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS antinuke_events (
            guild_id INTEGER NOT NULL,
            actor_id INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    await bot.db.execute(
        "CREATE INDEX IF NOT EXISTS idx_antinuke_events_actor "
        "ON antinuke_events (guild_id, actor_id, created_at)"
    )
    # Le rollback historique crée normalement cette table. On la garantit aussi ici afin
    # que les listeners V2 puissent démarrer dans n'importe quel ordre d'extensions.
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS antinuke_rollback_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            actor_id INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            target_id INTEGER,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL,
            handled INTEGER NOT NULL DEFAULT 0
        )
        """
    )


async def get_policy(bot: commands.Bot, guild_id: int) -> dict:
    row = await bot.db.fetchone(
        "SELECT action_threshold, window_seconds FROM antinuke_policy WHERE guild_id = ?",
        (guild_id,),
    )
    if not row:
        return {"action_threshold": DEFAULT_THRESHOLD, "window_seconds": DEFAULT_WINDOW}
    return {
        "action_threshold": max(MIN_THRESHOLD, min(MAX_THRESHOLD, int(row["action_threshold"]))),
        "window_seconds": max(MIN_WINDOW, min(MAX_WINDOW, int(row["window_seconds"]))),
    }


async def set_policy(
    bot: commands.Bot,
    guild_id: int,
    *,
    threshold: int,
    window: int,
    updated_by: int,
) -> dict:
    threshold = max(MIN_THRESHOLD, min(MAX_THRESHOLD, int(threshold)))
    window = max(MIN_WINDOW, min(MAX_WINDOW, int(window)))
    await bot.db.execute(
        """
        INSERT INTO antinuke_policy (guild_id, action_threshold, window_seconds, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            action_threshold = excluded.action_threshold,
            window_seconds = excluded.window_seconds,
            updated_by = excluded.updated_by,
            updated_at = excluded.updated_at
        """,
        (guild_id, threshold, window, updated_by, int(time.time())),
    )
    return {"action_threshold": threshold, "window_seconds": window}


def _role_snapshot(role: discord.Role) -> dict:
    return {
        "id": int(role.id),
        "name": role.name,
        "color": int(role.color.value),
        "permissions": int(role.permissions.value),
        "hoist": bool(role.hoist),
        "mentionable": bool(role.mentionable),
        "position": int(role.position),
        "member_ids": [int(member.id) for member in role.members[:500]],
    }


async def _record_rollback(
    bot: commands.Bot,
    guild_id: int,
    actor_id: int,
    action_type: str,
    target_id: int | None,
    payload: dict,
) -> None:
    try:
        await bot.db.execute(
            "INSERT INTO antinuke_rollback_actions "
            "(guild_id, actor_id, action_type, target_id, payload_json, created_at, handled) "
            "VALUES (?, ?, ?, ?, ?, ?, 0)",
            (
                guild_id,
                int(actor_id),
                action_type,
                int(target_id) if target_id is not None else None,
                json.dumps(payload, ensure_ascii=False),
                int(time.time()),
            ),
        )
    except Exception:
        logger.exception("Security V2 : impossible d'enregistrer le snapshot %s.", action_type)


async def _security_context(bot: commands.Bot, guild: discord.Guild, action, target_id: int | None):
    automod = bot.get_cog("Automod")
    if automod is None:
        return None, None
    try:
        conf = await automod.get_automod_cached(guild.id)
        if not conf or not conf.get("antinuke"):
            return automod, None
        actor = await automod.get_audit_actor(guild, action, target_id)
        if actor is None or await automod.is_antinuke_exempt(guild, actor):
            return automod, None
        return automod, actor
    except Exception:
        logger.exception("Security V2 : lecture du contexte anti-nuke impossible sur %s.", guild.id)
        return automod, None


class SecurityV2Runtime(commands.Cog, name=_COG_NAME):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._backup_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.auto_backup_watch.start()

    def cog_unload(self):
        self.auto_backup_watch.cancel()

    @tasks.loop(minutes=30)
    async def auto_backup_watch(self):
        now_ts = int(time.time())
        for guild in list(self.bot.guilds):
            try:
                automod = self.bot.get_cog("Automod")
                if automod is None:
                    return
                conf = await automod.get_automod_cached(guild.id)
                if not conf or not conf.get("antinuke"):
                    continue
                last = await self.bot.db.fetchone(
                    "SELECT created_at FROM server_backups "
                    "WHERE guild_id = ? AND label LIKE 'Auto Anti-Nuke%' "
                    "ORDER BY created_at DESC LIMIT 1",
                    (guild.id,),
                )
                if last and now_ts - int(last["created_at"] or 0) < AUTO_BACKUP_INTERVAL:
                    continue
                await self.create_auto_backup(guild)
                await asyncio.sleep(0.2)
            except Exception:
                logger.exception("Security V2 : sauvegarde automatique impossible sur %s.", guild.id)

    @auto_backup_watch.before_loop
    async def before_auto_backup_watch(self):
        try:
            await self.bot.wait_until_ready()
        except RuntimeError:
            # Audit CI : aucun login Discord réel n'est lancé.
            return

    async def create_auto_backup(self, guild: discord.Guild) -> int | None:
        lock = self._backup_locks[guild.id]
        async with lock:
            data = self._snapshot_server(guild)
            created_at = int(time.time())
            label = "Auto Anti-Nuke " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            creator_id = int(self.bot.user.id) if self.bot.user else 0
            cur = await self.bot.db.execute(
                "INSERT INTO server_backups (guild_id, label, data_json, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (guild.id, label, json.dumps(data, ensure_ascii=False), creator_id, created_at),
            )
            rows = await self.bot.db.fetchall(
                "SELECT id FROM server_backups WHERE guild_id = ? AND label LIKE 'Auto Anti-Nuke%' "
                "ORDER BY created_at DESC, id DESC",
                (guild.id,),
            )
            for stale in rows[AUTO_BACKUP_KEEP:]:
                await self.bot.db.execute("DELETE FROM server_backups WHERE id = ?", (stale["id"],))
            logger.info("Security V2 : sauvegarde auto #%s créée pour %s.", cur.lastrowid, guild.id)
            return int(cur.lastrowid)

    @staticmethod
    def _snapshot_server(guild: discord.Guild) -> dict:
        roles = [
            {
                "name": role.name,
                "color": int(role.color.value),
                "hoist": bool(role.hoist),
                "mentionable": bool(role.mentionable),
                "permissions": int(role.permissions.value),
                "position": int(role.position),
            }
            for role in guild.roles
            if role != guild.default_role and not role.managed
        ]
        categories = []
        for category in guild.categories:
            cat = {"name": category.name, "position": int(category.position), "channels": []}
            for channel in category.channels:
                item = {
                    "name": channel.name,
                    "type": "voice" if isinstance(channel, discord.VoiceChannel) else "text",
                    "position": int(channel.position),
                }
                if isinstance(channel, discord.TextChannel):
                    item.update({
                        "topic": channel.topic,
                        "nsfw": bool(channel.nsfw),
                        "slowmode_delay": int(channel.slowmode_delay),
                    })
                cat["channels"].append(item)
            categories.append(cat)
        uncategorized = [
            {
                "name": channel.name,
                "type": "voice" if isinstance(channel, discord.VoiceChannel) else "text",
                "position": int(channel.position),
            }
            for channel in guild.channels
            if channel.category is None
            and isinstance(channel, (discord.TextChannel, discord.VoiceChannel))
        ]
        return {"roles": roles, "categories": categories, "uncategorized": uncategorized}

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        _automod, actor = await _security_context(
            self.bot, role.guild, discord.AuditLogAction.role_delete, role.id
        )
        if actor is not None:
            await _record_rollback(
                self.bot, role.guild.id, actor.id, "role_delete", role.id, _role_snapshot(role)
            )

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        _automod, actor = await _security_context(
            self.bot, role.guild, discord.AuditLogAction.role_create, role.id
        )
        if actor is not None:
            await _record_rollback(
                self.bot, role.guild.id, actor.id, "role_create", role.id,
                {"id": int(role.id), "name": role.name},
            )

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        changed = (
            before.name != after.name
            or before.permissions != after.permissions
            or before.color != after.color
            or before.hoist != after.hoist
            or before.mentionable != after.mentionable
            or before.position != after.position
        )
        if not changed:
            return
        automod, actor = await _security_context(
            self.bot, after.guild, discord.AuditLogAction.role_update, after.id
        )
        if actor is None:
            return
        await _record_rollback(
            self.bot, after.guild.id, actor.id, "role_update", after.id, _role_snapshot(before)
        )
        # automod.py compte déjà les renommages et élévations de permissions. Les autres
        # mutations importantes sont comptées ici pour fermer le contournement.
        already_counted = before.name != after.name or before.permissions != after.permissions
        if not already_counted and automod is not None:
            try:
                if await automod.record_nuke_action(after.guild, actor.id):
                    await automod.punish_nuker(
                        after.guild, actor.id, "Modification massive de rôles"
                    )
            except Exception:
                logger.exception("Security V2 : déclenchement role_update impossible.")

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        if before.name == after.name:
            return
        automod, actor = await _security_context(
            self.bot, after, discord.AuditLogAction.guild_update, after.id
        )
        if actor is None:
            return
        await _record_rollback(
            self.bot,
            after.id,
            actor.id,
            "guild_update",
            after.id,
            {"name": before.name},
        )
        try:
            if await automod.record_nuke_action(after, actor.id):
                await automod.punish_nuker(after, actor.id, "Modification massive du serveur")
        except Exception:
            logger.exception("Security V2 : déclenchement guild_update impossible.")

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel):
        guild = channel.guild
        automod = self.bot.get_cog("Automod")
        if automod is None:
            return
        try:
            conf = await automod.get_automod_cached(guild.id)
            if not conf or not conf.get("antinuke"):
                return
            async for entry in guild.audit_logs(limit=3, action=discord.AuditLogAction.webhook_create):
                if (discord.utils.utcnow() - entry.created_at).total_seconds() > 12:
                    break
                actor = entry.user
                if actor is None or await automod.is_antinuke_exempt(guild, actor):
                    return
                target_id = int(getattr(entry.target, "id", 0) or 0)
                if not target_id:
                    return
                # Évite de dupliquer la même entrée quand Discord dispatch plusieurs updates.
                exists = await self.bot.db.fetchone(
                    "SELECT 1 FROM antinuke_rollback_actions "
                    "WHERE guild_id = ? AND actor_id = ? AND action_type = 'webhook_create' "
                    "AND target_id = ? AND created_at >= ?",
                    (guild.id, actor.id, target_id, int(time.time()) - 20),
                )
                if not exists:
                    await _record_rollback(
                        self.bot,
                        guild.id,
                        actor.id,
                        "webhook_create",
                        target_id,
                        {"id": target_id, "channel_id": int(channel.id)},
                    )
                return
        except (discord.Forbidden, discord.HTTPException):
            return
        except Exception:
            logger.exception("Security V2 : journalisation webhook impossible.")


async def _restore_v2_rows(bot: commands.Bot, guild: discord.Guild, actor_id: int) -> dict:
    cutoff = int(time.time()) - ROLLBACK_WINDOW
    rows = await bot.db.fetchall(
        "SELECT * FROM antinuke_rollback_actions "
        "WHERE guild_id = ? AND actor_id = ? AND handled = 0 AND created_at >= ? "
        "ORDER BY id DESC LIMIT 100",
        (guild.id, int(actor_id), cutoff),
    )
    result = {
        "roles_restored": 0,
        "roles_deleted": 0,
        "roles_reverted": 0,
        "guild_reverted": 0,
        "webhooks_deleted": 0,
    }
    parsed = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except Exception:
            payload = {}
        parsed.append((row, payload))

    # Supprimer les rôles malveillants créés en rafale.
    for row, payload in parsed:
        if row["action_type"] != "role_create":
            continue
        role = guild.get_role(int(row["target_id"] or payload.get("id") or 0))
        if role is None or role.managed or role >= guild.me.top_role:
            continue
        try:
            await role.delete(reason=f"SentriX Security V2 : rollback anti-nuke {actor_id}")
            result["roles_deleted"] += 1
        except (discord.Forbidden, discord.HTTPException):
            pass

    # Recréer les rôles supprimés. L'ID Discord d'un rôle supprimé ne peut pas être récupéré,
    # mais le nom, permissions, couleur, position et membres sont restaurés au mieux.
    restored_role_ids: dict[int, discord.Role] = {}
    delete_rows = [(row, payload) for row, payload in parsed if row["action_type"] == "role_delete"]
    delete_rows.reverse()
    for row, payload in delete_rows:
        old_id = int(payload.get("id") or row["target_id"] or 0)
        if discord.utils.get(guild.roles, name=str(payload.get("name") or "")):
            continue
        try:
            role = await guild.create_role(
                name=str(payload.get("name") or "Rôle restauré")[:100],
                permissions=discord.Permissions(permissions=int(payload.get("permissions") or 0)),
                colour=discord.Colour(int(payload.get("color") or 0)),
                hoist=bool(payload.get("hoist")),
                mentionable=bool(payload.get("mentionable")),
                reason=f"SentriX Security V2 : restauration rôle supprimé par {actor_id}",
            )
            try:
                await role.edit(position=max(1, int(payload.get("position") or 1)))
            except (discord.Forbidden, discord.HTTPException, TypeError, ValueError):
                pass
            if old_id:
                restored_role_ids[old_id] = role
            for member_id in payload.get("member_ids") or []:
                member = guild.get_member(int(member_id))
                if member is None or role >= guild.me.top_role:
                    continue
                try:
                    await member.add_roles(role, reason="SentriX Security V2 : restauration anti-nuke")
                except (discord.Forbidden, discord.HTTPException):
                    pass
            result["roles_restored"] += 1
        except (discord.Forbidden, discord.HTTPException, TypeError, ValueError):
            logger.exception("Security V2 : impossible de recréer un rôle supprimé.")

    # Revenir à l'état précédent pour les rôles toujours présents.
    for row, payload in parsed:
        if row["action_type"] != "role_update":
            continue
        role = guild.get_role(int(payload.get("id") or row["target_id"] or 0))
        if role is None or role.managed or role >= guild.me.top_role:
            continue
        try:
            await role.edit(
                name=str(payload.get("name") or role.name)[:100],
                permissions=discord.Permissions(permissions=int(payload.get("permissions") or 0)),
                colour=discord.Colour(int(payload.get("color") or 0)),
                hoist=bool(payload.get("hoist")),
                mentionable=bool(payload.get("mentionable")),
                position=max(1, int(payload.get("position") or role.position)),
                reason=f"SentriX Security V2 : annulation modification massive par {actor_id}",
            )
            result["roles_reverted"] += 1
        except (discord.Forbidden, discord.HTTPException, TypeError, ValueError):
            pass

    # Restaurer le nom du serveur s'il a été modifié pendant la rafale.
    for row, payload in parsed:
        if row["action_type"] != "guild_update":
            continue
        old_name = str(payload.get("name") or "").strip()
        if not old_name or guild.name == old_name:
            continue
        try:
            await guild.edit(name=old_name[:100], reason="SentriX Security V2 : rollback anti-nuke")
            result["guild_reverted"] += 1
        except (discord.Forbidden, discord.HTTPException):
            pass

    # Retirer les webhooks créés par l'attaquant dans la fenêtre de rollback.
    for row, payload in parsed:
        if row["action_type"] != "webhook_create":
            continue
        channel = guild.get_channel(int(payload.get("channel_id") or 0))
        target_id = int(payload.get("id") or row["target_id"] or 0)
        if channel is None or not hasattr(channel, "webhooks") or not target_id:
            continue
        try:
            hooks = await channel.webhooks()
            hook = discord.utils.get(hooks, id=target_id)
            if hook is not None:
                await hook.delete(reason="SentriX Security V2 : webhook créé pendant un nuke")
                result["webhooks_deleted"] += 1
        except (discord.Forbidden, discord.HTTPException):
            pass

    rollback = bot.get_cog("AntiNukeRollback")
    if rollback is not None:
        rollback._sentrix_v2_last_result = (guild.id, int(actor_id), result, int(time.time()))
    return result


def _patch_rollback(bot: commands.Bot) -> None:
    rollback = bot.get_cog("AntiNukeRollback")
    if rollback is None:
        return
    current = rollback.rollback_actor
    func = getattr(current, "__func__", current)
    if getattr(func, "_sentrix_v2_role_rollback", False):
        return

    async def rollback_with_v2(_self, guild: discord.Guild, actor_id: int, reason: str):
        try:
            await _restore_v2_rows(bot, guild, actor_id)
        except Exception:
            logger.exception("Security V2 : rollback rôles/serveur incomplet sur %s.", guild.id)
        result = await current(guild, actor_id, reason)
        extra = getattr(_self, "_sentrix_v2_last_result", None)
        if extra and extra[0] == guild.id and extra[1] == int(actor_id):
            try:
                result.update(extra[2])
            except Exception:
                pass
        return result

    rollback_with_v2._sentrix_v2_role_rollback = True
    rollback.rollback_actor = MethodType(rollback_with_v2, rollback)
    logger.info("Security V2 : rollback rôles/serveur branché.")


def _patch_dynamic_counter(bot: commands.Bot) -> None:
    automod = bot.get_cog("Automod")
    if automod is None:
        return
    current = automod.record_nuke_action
    func = getattr(current, "__func__", current)
    if getattr(func, "_sentrix_v2_dynamic_counter", False):
        return
    lock = asyncio.Lock()

    async def dynamic_record(_self, guild: discord.Guild, actor_id: int) -> bool:
        try:
            policy = await get_policy(bot, guild.id)
            threshold = policy["action_threshold"]
            window = policy["window_seconds"]
            now_ts = int(time.time())
            cutoff = now_ts - window
            async with lock:
                await bot.db.execute(
                    "DELETE FROM antinuke_events WHERE guild_id = ? AND created_at < ?",
                    (guild.id, cutoff),
                )
                await bot.db.execute(
                    "INSERT INTO antinuke_events (guild_id, actor_id, created_at) VALUES (?, ?, ?)",
                    (guild.id, int(actor_id), now_ts),
                )
                row = await bot.db.fetchone(
                    "SELECT COUNT(*) AS n FROM antinuke_events "
                    "WHERE guild_id = ? AND actor_id = ? AND created_at >= ?",
                    (guild.id, int(actor_id), cutoff),
                )
                count = int(row["n"] if row else 0)
                if count < threshold:
                    return False
                await bot.db.execute(
                    "DELETE FROM antinuke_events WHERE guild_id = ? AND actor_id = ?",
                    (guild.id, int(actor_id)),
                )
                try:
                    await bot.db.execute(
                        "INSERT INTO security_events "
                        "(guild_id, actor_id, event_type, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                        (
                            guild.id,
                            int(actor_id),
                            "antinuke_trigger_v2",
                            f"Seuil atteint: {count}/{threshold} action(s) en {window}s",
                            now_ts,
                        ),
                    )
                except Exception:
                    pass
                return True
        except Exception:
            logger.exception("Security V2 : compteur dynamique indisponible, fallback précédent.")
            return await current(guild, actor_id)

    dynamic_record._sentrix_v2_dynamic_counter = True
    automod.record_nuke_action = MethodType(dynamic_record, automod)
    logger.info("Security V2 : seuil anti-nuke dynamique activé.")


async def _write_incident(bot: commands.Bot, guild: discord.Guild, actor_id: int, reason: str) -> int | None:
    now_ts = int(time.time())
    recent = await bot.db.fetchone(
        "SELECT id FROM security_incidents WHERE guild_id = ? AND actor_id = ? AND created_at >= ? "
        "ORDER BY id DESC LIMIT 1",
        (guild.id, int(actor_id), now_ts - 20),
    )
    if recent:
        return int(recent["id"])
    summary = {}
    rollback = bot.get_cog("AntiNukeRollback")
    extra = getattr(rollback, "_sentrix_v2_last_result", None) if rollback else None
    if extra and extra[0] == guild.id and extra[1] == int(actor_id) and now_ts - extra[3] <= 30:
        summary.update(extra[2])
    cur = await bot.db.execute(
        "INSERT INTO security_incidents (guild_id, actor_id, reason, summary_json, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (guild.id, int(actor_id), reason[:500], json.dumps(summary, ensure_ascii=False), now_ts),
    )
    incident_id = int(cur.lastrowid)
    automod = bot.get_cog("Automod")
    if automod is not None:
        try:
            await automod.log_action(
                guild,
                embeds.log_entry(
                    f"Incident sécurité #{incident_id}",
                    discord.Color.red(),
                    cible=guild.get_member(actor_id) or actor_id,
                    cible_label="Auteur détecté",
                    raison=reason,
                    extra={
                        "Rôles recréés": str(summary.get("roles_restored", 0)),
                        "Rôles malveillants supprimés": str(summary.get("roles_deleted", 0)),
                        "Rôles restaurés": str(summary.get("roles_reverted", 0)),
                        "Nom serveur restauré": str(summary.get("guild_reverted", 0)),
                        "Webhooks supprimés": str(summary.get("webhooks_deleted", 0)),
                    },
                ),
            )
        except Exception:
            pass
    return incident_id


def _patch_incidents(bot: commands.Bot) -> None:
    automod = bot.get_cog("Automod")
    if automod is None:
        return
    current = automod.punish_nuker
    func = getattr(current, "__func__", current)
    if getattr(func, "_sentrix_v2_incident_wrapper", False):
        return

    async def punish_with_incident(_self, guild: discord.Guild, actor_id: int, reason: str):
        try:
            result = await current(guild, actor_id, reason)
        finally:
            try:
                await _write_incident(bot, guild, actor_id, reason)
            except Exception:
                logger.exception("Security V2 : impossible d'enregistrer l'incident.")
        return result

    punish_with_incident._sentrix_v2_incident_wrapper = True
    automod.punish_nuker = MethodType(punish_with_incident, automod)
    logger.info("Security V2 : journal d'incidents branché.")


async def _is_security_staff(ctx: commands.Context) -> bool:
    if ctx.guild is None:
        return False
    if ctx.author.id == ctx.guild.owner_id:
        return True
    return bool(getattr(ctx.author.guild_permissions, "administrator", False))


async def _send_health(bot: commands.Bot, ctx: commands.Context) -> None:
    if not await _is_security_staff(ctx):
        return await ctx.send(embed=embeds.error("Cette commande est réservée au propriétaire ou aux administrateurs."))
    db_ok = True
    try:
        await bot.db.fetchone("SELECT 1 AS ok")
    except Exception:
        db_ok = False
    required_cogs = ["Automod", "SecurityHardening", "AntiNukeRollback", _COG_NAME]
    loaded = {name: bool(bot.get_cog(name)) for name in required_cogs}
    me = ctx.guild.me
    perms = {
        "Audit log": bool(me and me.guild_permissions.view_audit_log),
        "Ban": bool(me and me.guild_permissions.ban_members),
        "Rôles": bool(me and me.guild_permissions.manage_roles),
        "Salons": bool(me and me.guild_permissions.manage_channels),
        "Messages": bool(me and me.guild_permissions.manage_messages),
    }
    policy = await get_policy(bot, ctx.guild.id)
    last_backup = await bot.db.fetchone(
        "SELECT id, created_at FROM server_backups WHERE guild_id = ? AND label LIKE 'Auto Anti-Nuke%' "
        "ORDER BY created_at DESC LIMIT 1",
        (ctx.guild.id,),
    )
    e = embeds.neutral(
        "SentriX Health",
        f"Latence Discord : **{round(bot.latency * 1000)} ms**\n"
        f"Base SQLite : **{'OK' if db_ok else 'ERREUR'}**\n"
        f"Seuil anti-nuke : **{policy['action_threshold']} actions / {policy['window_seconds']}s**",
    )
    e.add_field(
        name="Moteurs",
        value="\n".join(f"{'✅' if ok else '❌'} {name}" for name, ok in loaded.items()),
        inline=False,
    )
    e.add_field(
        name="Permissions critiques",
        value="\n".join(f"{'✅' if ok else '❌'} {name}" for name, ok in perms.items()),
        inline=False,
    )
    if last_backup:
        e.add_field(
            name="Dernière sauvegarde auto",
            value=f"#{last_backup['id']} · <t:{int(last_backup['created_at'])}:R>",
            inline=False,
        )
    await ctx.send(embed=e)


def _install_commands(bot: commands.Bot) -> None:
    if bot.get_command("health") is None:
        @commands.command(name="health", help="Diagnostiquer l'état technique de SentriX.")
        @commands.guild_only()
        async def health(ctx: commands.Context):
            await _send_health(bot, ctx)
        bot.add_command(health)

    root = bot.get_command("security")
    if not isinstance(root, commands.Group):
        return

    if root.get_command("health") is None:
        @commands.command(name="health")
        async def security_health(ctx: commands.Context):
            await _send_health(bot, ctx)
        root.add_command(security_health)

    if root.get_command("incidents") is None:
        @commands.command(name="incidents", aliases=["incident"])
        async def incidents(ctx: commands.Context, limit: int = 10):
            if not await _is_security_staff(ctx):
                return await ctx.send(embed=embeds.error("Accès administrateur requis."))
            limit = max(1, min(20, int(limit)))
            rows = await bot.db.fetchall(
                "SELECT id, actor_id, reason, summary_json, created_at FROM security_incidents "
                "WHERE guild_id = ? ORDER BY id DESC LIMIT ?",
                (ctx.guild.id, limit),
            )
            if not rows:
                return await ctx.send(embed=embeds.info("Aucun incident anti-nuke enregistré."))
            lines = []
            for row in rows:
                lines.append(
                    f"**#{row['id']}** · <t:{int(row['created_at'])}:R> · <@{row['actor_id']}>\n"
                    f"╰ {str(row['reason'])[:180]}"
                )
            await ctx.send(embed=embeds.neutral("Incidents anti-nuke", "\n\n".join(lines)[:4000]))
        root.add_command(incidents)

    if root.get_command("antinuke-config") is None:
        @commands.command(name="antinuke-config", aliases=["nuke-config"])
        async def antinuke_config(ctx: commands.Context, threshold: int | None = None, window: int | None = None):
            if ctx.guild is None:
                return
            if ctx.author.id != ctx.guild.owner_id:
                return await ctx.send(embed=embeds.error("Seul le propriétaire du serveur peut modifier le seuil anti-nuke."))
            current = await get_policy(bot, ctx.guild.id)
            if threshold is None and window is None:
                return await ctx.send(embed=embeds.neutral(
                    "Configuration anti-nuke",
                    f"Seuil actuel : **{current['action_threshold']} actions en {current['window_seconds']} secondes**.\n"
                    f"Utilise `+security antinuke-config 3 30`.\n"
                    f"Limites : {MIN_THRESHOLD}-{MAX_THRESHOLD} actions, {MIN_WINDOW}-{MAX_WINDOW} secondes.",
                ))
            threshold = current["action_threshold"] if threshold is None else threshold
            window = current["window_seconds"] if window is None else window
            saved = await set_policy(
                bot, ctx.guild.id, threshold=threshold, window=window, updated_by=ctx.author.id
            )
            await ctx.send(embed=embeds.success(
                f"Anti-nuke réglé sur **{saved['action_threshold']} actions en {saved['window_seconds']} secondes**."
            ))
        root.add_command(antinuke_config)

    if root.get_command("backup-now") is None:
        @commands.command(name="backup-now", aliases=["backup-auto"])
        async def backup_now(ctx: commands.Context):
            if not await _is_security_staff(ctx):
                return await ctx.send(embed=embeds.error("Accès administrateur requis."))
            runtime = bot.get_cog(_COG_NAME)
            if runtime is None:
                return await ctx.send(embed=embeds.error("Moteur de sauvegarde indisponible."))
            backup_id = await runtime.create_auto_backup(ctx.guild)
            await ctx.send(embed=embeds.success(f"Sauvegarde de sécurité **#{backup_id}** créée."))
        root.add_command(backup_now)


async def _late_repatch(bot: commands.Bot) -> None:
    # Plusieurs couches runtime remplacent les mêmes méthodes pendant setup_hook(). On repasse
    # quelques fois sans bloquer le démarrage afin que Security V2 reste la couche finale.
    for _ in range(6):
        await asyncio.sleep(1)
        try:
            _patch_dynamic_counter(bot)
            _patch_rollback(bot)
            _patch_incidents(bot)
            _install_commands(bot)
        except Exception:
            logger.exception("Security V2 : repatch différé incomplet.")


async def install(bot: commands.Bot) -> None:
    await _ensure_tables(bot)
    if bot.get_cog(_COG_NAME) is None:
        await bot.add_cog(SecurityV2Runtime(bot))
        logger.info("Security V2 Runtime chargé.")
    _patch_dynamic_counter(bot)
    _patch_rollback(bot)
    _patch_incidents(bot)
    _install_commands(bot)
    if not getattr(bot, "_sentrix_security_v2_repatch_task", False):
        bot._sentrix_security_v2_repatch_task = True
        try:
            asyncio.create_task(_late_repatch(bot), name="sentrix-security-v2-repatch")
        except RuntimeError:
            pass
