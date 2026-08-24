"""Anti-nuke V55: attribution fiable, confinement immédiat et restauration complète.

Objectifs :
- retrouver l'auteur réel d'une rafale via les logs d'audit, même si Discord les publie
  avec un léger retard ;
- bannir/neutraliser l'auteur AVANT de commencer la restauration ;
- mémoriser les dégâts au fil des événements Discord ;
- restaurer rôles, catégories, salons, permissions et victimes bannies sur plusieurs
  passes afin de récupérer aussi les événements arrivés en retard.

Cette couche ne change pas le seuil anti-nuke historique d'AutoMod : elle rend son
attribution et son rollback beaucoup plus robustes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from types import MethodType
from typing import Any

import discord
from discord.ext import commands

from utils import embeds

logger = logging.getLogger("bot.security.antinuke-v55")

_COG_NAME = "AntiNukeEmergencyV55"
_TABLE = "antinuke_v55_damage"

# Un serveur Discord peut avoir plusieurs centaines de salons. 80 lignes, comme dans
# l'ancien rollback, tronquait une vraie destruction massive.
DAMAGE_WINDOW_SECONDS = 180
MAX_DAMAGE_ROWS = 1500
PURGE_AFTER_SECONDS = 900

# Les Audit Logs Discord ne sont pas toujours visibles au même instant que l'événement.
AUDIT_LOOKBACK_SECONDS = 90
AUDIT_SCAN_LIMIT = 100
AUDIT_CACHE_TTL = 18.0
AUDIT_RETRY_DELAYS = (0.0, 0.18, 0.45, 0.85, 1.35)

# Après le ban, plusieurs passes récupèrent les listeners/audits encore en vol.
RESTORE_DRAIN_DELAYS = (0.45, 0.90, 1.60, 2.40)
PUNISH_COOLDOWN_SECONDS = 20.0
CREATE_RETRIES = 3


def _action_key(action: discord.AuditLogAction) -> int | str:
    value = getattr(action, "value", None)
    return value if value is not None else str(action)


def _target_id(entry: discord.AuditLogEntry) -> int | None:
    target = getattr(entry, "target", None)
    value = getattr(target, "id", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _permission_overwrites_snapshot(channel: discord.abc.GuildChannel) -> list[dict[str, Any]]:
    """Capture les overwrites même si le rôle ciblé vient déjà d'être supprimé."""
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    # discord.py conserve la forme brute des overwrites avec l'ID de la cible. Cette voie
    # est importante pendant un nuke : guild.get_role(id) peut déjà renvoyer None.
    for raw in list(getattr(channel, "_overwrites", []) or []):
        try:
            target_id = int(raw.id)
            raw_type = int(raw.type)
            target_type = "role" if raw_type == 0 else "member"
            key = (target_type, target_id)
            if key in seen:
                continue
            seen.add(key)
            result.append(
                {
                    "id": target_id,
                    "type": target_type,
                    "allow": int(raw.allow),
                    "deny": int(raw.deny),
                }
            )
        except Exception:
            continue

    # Repli public pour compatibilité avec d'autres versions de discord.py.
    try:
        items = channel.overwrites.items()
    except Exception:
        items = []
    for target, overwrite in items:
        try:
            target_type = "role" if isinstance(target, discord.Role) else "member"
            target_id = int(target.id)
            key = (target_type, target_id)
            if key in seen:
                continue
            allow, deny = overwrite.pair()
            seen.add(key)
            result.append(
                {
                    "id": target_id,
                    "type": target_type,
                    "allow": int(allow.value),
                    "deny": int(deny.value),
                }
            )
        except Exception:
            continue
    return result


def _channel_kind(channel: discord.abc.GuildChannel) -> str:
    if isinstance(channel, discord.CategoryChannel):
        return "category"
    if isinstance(channel, discord.StageChannel):
        return "stage"
    if isinstance(channel, discord.VoiceChannel):
        return "voice"
    forum_cls = getattr(discord, "ForumChannel", None)
    if forum_cls is not None and isinstance(channel, forum_cls):
        return "forum"
    if isinstance(channel, discord.TextChannel):
        return "news" if channel.is_news() else "text"
    return "unknown"


def _channel_snapshot(channel: discord.abc.GuildChannel) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": int(channel.id),
        "kind": _channel_kind(channel),
        "name": str(channel.name),
        "position": int(getattr(channel, "position", 0) or 0),
        "category_id": int(channel.category_id) if getattr(channel, "category_id", None) else None,
        "overwrites": _permission_overwrites_snapshot(channel),
    }
    if isinstance(channel, discord.CategoryChannel):
        data["child_ids"] = [int(child.id) for child in list(channel.channels)]
        return data

    for attr in (
        "topic",
        "nsfw",
        "slowmode_delay",
        "default_auto_archive_duration",
        "default_thread_slowmode_delay",
        "bitrate",
        "user_limit",
    ):
        if hasattr(channel, attr):
            value = getattr(channel, attr)
            if isinstance(value, (str, int, bool)) or value is None:
                data[attr] = value

    rtc_region = getattr(channel, "rtc_region", None)
    if rtc_region is not None:
        data["rtc_region"] = str(rtc_region)
    video_quality = getattr(channel, "video_quality_mode", None)
    if video_quality is not None:
        data["video_quality_mode"] = int(getattr(video_quality, "value", video_quality))
    return data


def _channel_update_snapshot(channel: discord.abc.GuildChannel) -> dict[str, Any]:
    return _channel_snapshot(channel)


def _role_snapshot(role: discord.Role) -> dict[str, Any]:
    return {
        "id": int(role.id),
        "name": str(role.name),
        "permissions": int(role.permissions.value),
        "colour": int(role.colour.value),
        "hoist": bool(role.hoist),
        "mentionable": bool(role.mentionable),
        "position": int(role.position),
        "managed": bool(role.managed),
    }


async def _ensure_table(bot: commands.Bot) -> None:
    await bot.db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            actor_id INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            target_id INTEGER,
            payload_json TEXT NOT NULL DEFAULT '{{}}',
            created_at INTEGER NOT NULL,
            handled INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    await bot.db.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_actor "
        f"ON {_TABLE} (guild_id, actor_id, handled, created_at)"
    )


def _patch_audit_actor(bot: commands.Bot) -> None:
    """Remplace la lecture audit limitée à 5 entrées par un resolver rafale + cache."""
    automod = bot.get_cog("Automod")
    if automod is None or getattr(automod, "_sentrix_audit_actor_v55", False):
        return

    cache: dict[tuple[int, int | str, int], tuple[float, discord.abc.User]] = {}
    locks: dict[tuple[int, int | str], asyncio.Lock] = defaultdict(asyncio.Lock)

    cacheable_actions = {
        discord.AuditLogAction.channel_delete,
        discord.AuditLogAction.channel_create,
        discord.AuditLogAction.role_delete,
        discord.AuditLogAction.role_create,
        discord.AuditLogAction.ban,
    }

    async def robust_get_audit_actor(
        _self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        target_id: int | None = None,
    ):
        action_key = _action_key(action)
        normalized_target = int(target_id) if target_id is not None else 0
        lookup_key = (guild.id, action_key, normalized_target)
        now = time.monotonic()

        cached = cache.get(lookup_key)
        if cached and cached[0] > now:
            return cached[1]
        if cached:
            cache.pop(lookup_key, None)

        lock = locks[(guild.id, action_key)]
        async with lock:
            now = time.monotonic()
            cached = cache.get(lookup_key)
            if cached and cached[0] > now:
                return cached[1]

            retries = AUDIT_RETRY_DELAYS if target_id is not None else (0.0, 0.25)
            for delay in retries:
                if delay:
                    await asyncio.sleep(delay)
                try:
                    chosen = None
                    async for entry in guild.audit_logs(limit=AUDIT_SCAN_LIMIT, action=action):
                        age = (discord.utils.utcnow() - entry.created_at).total_seconds()
                        if age > AUDIT_LOOKBACK_SECONDS:
                            break
                        entry_actor = getattr(entry, "user", None)
                        if entry_actor is None:
                            continue
                        entry_target_id = _target_id(entry)

                        if action in cacheable_actions and entry_target_id is not None:
                            cache[(guild.id, action_key, entry_target_id)] = (
                                time.monotonic() + AUDIT_CACHE_TTL,
                                entry_actor,
                            )

                        if target_id is None and chosen is None:
                            chosen = entry_actor
                        elif target_id is not None and entry_target_id == int(target_id):
                            chosen = entry_actor

                    if chosen is not None:
                        cache[lookup_key] = (time.monotonic() + AUDIT_CACHE_TTL, chosen)
                        return chosen
                except discord.HTTPException as exc:
                    logger.warning(
                        "Anti-nuke V55: audit log indisponible pour %s sur %s (%s): %s",
                        action,
                        guild.name,
                        guild.id,
                        exc,
                    )
                    continue
                except Exception:
                    logger.exception(
                        "Anti-nuke V55: erreur inattendue pendant l'attribution audit sur %s.",
                        guild.id,
                    )
                    continue
            return None

    automod.get_audit_actor = MethodType(robust_get_audit_actor, automod)
    automod._sentrix_audit_actor_v55 = True
    logger.info("Anti-nuke V55: attribution Audit Log 100 entrées + cache/retries activée.")


class AntiNukeEmergencyV55(commands.Cog, name=_COG_NAME):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._restore_locks: dict[tuple[int, int], asyncio.Lock] = defaultdict(asyncio.Lock)
        self._late_tasks: set[asyncio.Task] = set()
        self._last_summary: dict[tuple[int, int], float] = {}

    async def cog_unload(self) -> None:
        for task in list(self._late_tasks):
            task.cancel()

    async def _context(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        target_id: int | None,
    ):
        automod = self.bot.get_cog("Automod")
        if automod is None:
            return None, None
        try:
            conf = await automod.get_automod_cached(guild.id)
        except Exception:
            return automod, None
        if not conf or not conf.get("antinuke"):
            return automod, None
        actor = await automod.get_audit_actor(guild, action, target_id)
        if actor is None:
            return automod, None
        try:
            if await automod.is_antinuke_exempt(guild, actor):
                return automod, None
        except Exception:
            return automod, None
        return automod, actor

    async def _record(
        self,
        guild: discord.Guild,
        actor_id: int,
        action_type: str,
        target_id: int | None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        now_ts = int(time.time())
        try:
            await self.bot.db.execute(
                f"DELETE FROM {_TABLE} WHERE created_at < ? OR (handled = 1 AND created_at < ?)",
                (now_ts - PURGE_AFTER_SECONDS, now_ts - 60),
            )
            await self.bot.db.execute(
                f"INSERT INTO {_TABLE} "
                "(guild_id, actor_id, action_type, target_id, payload_json, created_at, handled) "
                "VALUES (?, ?, ?, ?, ?, ?, 0)",
                (
                    guild.id,
                    int(actor_id),
                    action_type,
                    int(target_id) if target_id is not None else None,
                    json.dumps(payload or {}, ensure_ascii=False),
                    now_ts,
                ),
            )
        except Exception:
            logger.exception("Anti-nuke V55: impossible d'enregistrer un dégât sur %s.", guild.id)

    def _schedule_late_record(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        target_id: int,
        action_type: str,
        payload: dict[str, Any],
    ) -> None:
        async def worker():
            await asyncio.sleep(2.2)
            automod = self.bot.get_cog("Automod")
            if automod is None:
                return
            actor = await automod.get_audit_actor(guild, action, target_id)
            if actor is None:
                return
            try:
                if await automod.is_antinuke_exempt(guild, actor):
                    return
            except Exception:
                return
            await self._record(guild, actor.id, action_type, target_id, payload)

        task = asyncio.create_task(worker(), name=f"sentrix-v55-late-{guild.id}-{target_id}")
        self._late_tasks.add(task)
        task.add_done_callback(self._late_tasks.discard)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        snapshot = _channel_snapshot(channel)
        _automod, actor = await self._context(
            channel.guild, discord.AuditLogAction.channel_delete, channel.id
        )
        if actor is None:
            self._schedule_late_record(
                channel.guild,
                discord.AuditLogAction.channel_delete,
                channel.id,
                "channel_delete",
                snapshot,
            )
            return
        await self._record(channel.guild, actor.id, "channel_delete", channel.id, snapshot)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        _automod, actor = await self._context(
            channel.guild, discord.AuditLogAction.channel_create, channel.id
        )
        if actor is None:
            return
        await self._record(
            channel.guild,
            actor.id,
            "channel_create",
            channel.id,
            {"id": int(channel.id), "name": channel.name, "kind": _channel_kind(channel)},
        )

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self,
        before: discord.abc.GuildChannel,
        after: discord.abc.GuildChannel,
    ):
        if (
            before.name == after.name
            and before.overwrites == after.overwrites
            and getattr(before, "category_id", None) == getattr(after, "category_id", None)
        ):
            return
        snapshot = _channel_update_snapshot(before)
        _automod, actor = await self._context(
            after.guild, discord.AuditLogAction.channel_update, after.id
        )
        if actor is None:
            return
        await self._record(after.guild, actor.id, "channel_update", after.id, snapshot)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        if role.is_default():
            return
        snapshot = _role_snapshot(role)
        _automod, actor = await self._context(
            role.guild, discord.AuditLogAction.role_delete, role.id
        )
        if actor is None:
            self._schedule_late_record(
                role.guild,
                discord.AuditLogAction.role_delete,
                role.id,
                "role_delete",
                snapshot,
            )
            return
        await self._record(role.guild, actor.id, "role_delete", role.id, snapshot)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        if role.is_default():
            return
        _automod, actor = await self._context(
            role.guild, discord.AuditLogAction.role_create, role.id
        )
        if actor is None:
            return
        await self._record(
            role.guild,
            actor.id,
            "role_create",
            role.id,
            {"id": int(role.id), "name": role.name, "managed": bool(role.managed)},
        )

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        if (
            before.name == after.name
            and before.permissions == after.permissions
            and before.colour == after.colour
            and before.hoist == after.hoist
            and before.mentionable == after.mentionable
        ):
            return
        snapshot = _role_snapshot(before)
        _automod, actor = await self._context(
            after.guild, discord.AuditLogAction.role_update, after.id
        )
        if actor is None:
            return
        await self._record(after.guild, actor.id, "role_update", after.id, snapshot)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        _automod, actor = await self._context(guild, discord.AuditLogAction.ban, user.id)
        if actor is None:
            return
        await self._record(guild, actor.id, "ban", user.id, {"user_id": int(user.id)})

    def _restore_overwrites(
        self,
        guild: discord.Guild,
        raw: list[dict[str, Any]] | None,
        role_map: dict[int, discord.Role],
    ) -> dict[Any, discord.PermissionOverwrite]:
        result: dict[Any, discord.PermissionOverwrite] = {}
        for item in raw or []:
            try:
                target_id = int(item["id"])
                if item.get("type") == "role":
                    target = role_map.get(target_id) or guild.get_role(target_id)
                else:
                    target = guild.get_member(target_id)
                if target is None:
                    continue
                allow = discord.Permissions(permissions=int(item.get("allow", 0)))
                deny = discord.Permissions(permissions=int(item.get("deny", 0)))
                result[target] = discord.PermissionOverwrite.from_pair(allow, deny)
            except Exception:
                continue
        return result

    async def _retry_create(self, factory, *, label: str, **kwargs):
        last_exc = None
        for attempt in range(CREATE_RETRIES):
            try:
                return await factory(**kwargs)
            except discord.Forbidden:
                raise
            except (discord.HTTPException, TypeError, ValueError) as exc:
                last_exc = exc
                if attempt + 1 < CREATE_RETRIES:
                    await asyncio.sleep(0.35 * (attempt + 1))
        if last_exc is not None:
            raise last_exc
        return None

    async def _restore_role(
        self,
        guild: discord.Guild,
        snapshot: dict[str, Any],
        role_map: dict[int, discord.Role],
    ) -> discord.Role | None:
        old_id = int(snapshot.get("id") or 0)
        existing = guild.get_role(old_id)
        if existing is not None:
            role_map[old_id] = existing
            return existing
        if bool(snapshot.get("managed")):
            return None

        reason = "SentriX anti-nuke V55 : restauration automatique d'un rôle supprimé"
        try:
            role = await self._retry_create(
                guild.create_role,
                label=f"role:{old_id}",
                name=str(snapshot.get("name") or "rôle-restauré")[:100],
                permissions=discord.Permissions(permissions=int(snapshot.get("permissions") or 0)),
                colour=discord.Colour(int(snapshot.get("colour") or 0)),
                hoist=bool(snapshot.get("hoist") or False),
                mentionable=bool(snapshot.get("mentionable") or False),
                reason=reason,
            )
        except (discord.Forbidden, discord.HTTPException, TypeError, ValueError):
            logger.exception("Anti-nuke V55: impossible de recréer le rôle %s sur %s.", old_id, guild.id)
            return None
        if old_id:
            role_map[old_id] = role
        try:
            await role.edit(position=max(1, int(snapshot.get("position") or 1)), reason=reason)
        except (discord.Forbidden, discord.HTTPException, TypeError, ValueError):
            pass
        return role

    async def _restore_deleted_channel(
        self,
        guild: discord.Guild,
        snapshot: dict[str, Any],
        channel_map: dict[int, discord.abc.GuildChannel],
        role_map: dict[int, discord.Role],
    ) -> discord.abc.GuildChannel | None:
        old_id = int(snapshot.get("id") or 0)
        if old_id in channel_map:
            return channel_map[old_id]
        existing = guild.get_channel(old_id) if old_id else None
        if existing is not None:
            channel_map[old_id] = existing
            return existing

        kind = str(snapshot.get("kind") or "text")
        name = str(snapshot.get("name") or "salon-restauré")[:100]
        position = max(0, int(snapshot.get("position") or 0))
        overwrites = self._restore_overwrites(guild, snapshot.get("overwrites"), role_map)
        reason = "SentriX anti-nuke V55 : restauration automatique d'un salon supprimé"

        category = None
        old_category_id = snapshot.get("category_id")
        if old_category_id:
            category = channel_map.get(int(old_category_id)) or guild.get_channel(int(old_category_id))
            if not isinstance(category, discord.CategoryChannel):
                category = None

        common = {"name": name, "overwrites": overwrites, "position": position, "reason": reason}
        try:
            if kind == "category":
                created = await self._retry_create(guild.create_category, label=name, **common)
            elif kind == "voice":
                rich = dict(
                    common,
                    category=category,
                    bitrate=int(snapshot.get("bitrate") or 64000),
                    user_limit=int(snapshot.get("user_limit") or 0),
                )
                created = await self._retry_create(guild.create_voice_channel, label=name, **rich)
            elif kind == "stage":
                rich = dict(common, category=category)
                created = await self._retry_create(guild.create_stage_channel, label=name, **rich)
            elif kind == "forum" and hasattr(guild, "create_forum_channel"):
                rich = dict(
                    common,
                    category=category,
                    topic=snapshot.get("topic"),
                    nsfw=bool(snapshot.get("nsfw") or False),
                    slowmode_delay=int(snapshot.get("slowmode_delay") or 0),
                    default_auto_archive_duration=int(snapshot.get("default_auto_archive_duration") or 1440),
                    default_thread_slowmode_delay=int(snapshot.get("default_thread_slowmode_delay") or 0),
                )
                created = await self._retry_create(guild.create_forum_channel, label=name, **rich)
            else:
                rich = dict(
                    common,
                    category=category,
                    topic=snapshot.get("topic"),
                    nsfw=bool(snapshot.get("nsfw") or False),
                    slowmode_delay=int(snapshot.get("slowmode_delay") or 0),
                    default_auto_archive_duration=int(snapshot.get("default_auto_archive_duration") or 1440),
                    default_thread_slowmode_delay=int(snapshot.get("default_thread_slowmode_delay") or 0),
                )
                if kind == "news":
                    rich["news"] = True
                created = await self._retry_create(guild.create_text_channel, label=name, **rich)
        except (discord.Forbidden, discord.HTTPException, TypeError, ValueError):
            try:
                if kind == "category":
                    created = await guild.create_category(name, overwrites=overwrites, reason=reason)
                elif kind == "voice":
                    created = await guild.create_voice_channel(name, category=category, overwrites=overwrites, reason=reason)
                elif kind == "stage":
                    created = await guild.create_stage_channel(name, category=category, overwrites=overwrites, reason=reason)
                elif kind == "forum" and hasattr(guild, "create_forum_channel"):
                    created = await guild.create_forum_channel(name, category=category, overwrites=overwrites, reason=reason)
                else:
                    created = await guild.create_text_channel(name, category=category, overwrites=overwrites, reason=reason)
            except (discord.Forbidden, discord.HTTPException, TypeError, ValueError):
                logger.exception("Anti-nuke V55: impossible de recréer %s (%s) sur %s.", name, old_id, guild.id)
                return None

        if old_id:
            channel_map[old_id] = created
        return created

    async def _restore_channel_state(
        self,
        guild: discord.Guild,
        snapshot: dict[str, Any],
        channel_map: dict[int, discord.abc.GuildChannel],
        role_map: dict[int, discord.Role],
    ) -> bool:
        old_id = int(snapshot.get("id") or 0)
        channel = channel_map.get(old_id) or guild.get_channel(old_id)
        if channel is None:
            return False
        reason = "SentriX anti-nuke V55 : restauration de la configuration du salon"
        kwargs: dict[str, Any] = {
            "name": str(snapshot.get("name") or channel.name)[:100],
            "overwrites": self._restore_overwrites(guild, snapshot.get("overwrites"), role_map),
            "position": max(0, int(snapshot.get("position") or 0)),
            "reason": reason,
        }
        if not isinstance(channel, discord.CategoryChannel):
            old_category_id = snapshot.get("category_id")
            category = None
            if old_category_id:
                candidate = channel_map.get(int(old_category_id)) or guild.get_channel(int(old_category_id))
                if isinstance(candidate, discord.CategoryChannel):
                    category = candidate
            kwargs["category"] = category

        if isinstance(channel, discord.TextChannel):
            kwargs["topic"] = snapshot.get("topic")
            kwargs["nsfw"] = bool(snapshot.get("nsfw") or False)
            kwargs["slowmode_delay"] = int(snapshot.get("slowmode_delay") or 0)
        elif isinstance(channel, discord.VoiceChannel):
            if snapshot.get("bitrate") is not None:
                kwargs["bitrate"] = int(snapshot["bitrate"])
            if snapshot.get("user_limit") is not None:
                kwargs["user_limit"] = int(snapshot["user_limit"])

        try:
            await channel.edit(**kwargs)
            return True
        except (discord.Forbidden, discord.HTTPException, TypeError, ValueError):
            safe = {
                "overwrites": kwargs["overwrites"],
                "position": kwargs["position"],
                "reason": reason,
            }
            if "category" in kwargs:
                safe["category"] = kwargs["category"]
            try:
                await channel.edit(**safe)
                return True
            except (discord.Forbidden, discord.HTTPException, TypeError, ValueError):
                return False

    async def _restore_role_state(
        self,
        guild: discord.Guild,
        snapshot: dict[str, Any],
        role_map: dict[int, discord.Role],
    ) -> bool:
        old_id = int(snapshot.get("id") or 0)
        role = role_map.get(old_id) or guild.get_role(old_id)
        if role is None or role.managed or role.is_default():
            return False
        try:
            await role.edit(
                name=str(snapshot.get("name") or role.name)[:100],
                permissions=discord.Permissions(permissions=int(snapshot.get("permissions") or 0)),
                colour=discord.Colour(int(snapshot.get("colour") or 0)),
                hoist=bool(snapshot.get("hoist") or False),
                mentionable=bool(snapshot.get("mentionable") or False),
                position=max(1, int(snapshot.get("position") or 1)),
                reason="SentriX anti-nuke V55 : restauration d'un rôle modifié",
            )
            return True
        except (discord.Forbidden, discord.HTTPException, TypeError, ValueError):
            return False

    async def _rollback_once(
        self,
        guild: discord.Guild,
        actor_id: int,
        channel_map: dict[int, discord.abc.GuildChannel],
        role_map: dict[int, discord.Role],
        channel_snapshots: dict[int, dict[str, Any]],
    ) -> dict[str, int]:
        cutoff = int(time.time()) - DAMAGE_WINDOW_SECONDS
        rows = await self.bot.db.fetchall(
            f"SELECT * FROM {_TABLE} "
            "WHERE guild_id = ? AND actor_id = ? AND handled = 0 AND created_at >= ? "
            "ORDER BY id DESC LIMIT ?",
            (guild.id, int(actor_id), cutoff, MAX_DAMAGE_ROWS),
        )
        result = {
            "unbanned": 0,
            "channels_restored": 0,
            "channels_deleted": 0,
            "channels_reverted": 0,
            "roles_restored": 0,
            "roles_deleted": 0,
            "roles_reverted": 0,
            "failed": 0,
        }
        if not rows:
            return result

        parsed: list[tuple[Any, dict[str, Any]]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except (TypeError, ValueError):
                payload = {}
            parsed.append((row, payload))
            if row["action_type"] == "channel_delete":
                old_id = int(row["target_id"] or payload.get("id") or 0)
                if old_id:
                    channel_snapshots[old_id] = payload

        handled_ids: set[int] = set()

        for row, payload in parsed:
            if row["action_type"] != "ban":
                continue
            target_id = int(row["target_id"] or payload.get("user_id") or 0)
            if not target_id or target_id == int(actor_id):
                handled_ids.add(int(row["id"]))
                continue
            try:
                await guild.unban(
                    discord.Object(id=target_id),
                    reason=f"SentriX anti-nuke V55 : annulation du nuke de {actor_id}",
                )
                result["unbanned"] += 1
                handled_ids.add(int(row["id"]))
            except discord.NotFound:
                handled_ids.add(int(row["id"]))
            except (discord.Forbidden, discord.HTTPException):
                result["failed"] += 1

        for row, payload in parsed:
            if row["action_type"] == "channel_create":
                target_id = int(row["target_id"] or payload.get("id") or 0)
                channel = guild.get_channel(target_id)
                if channel is None:
                    handled_ids.add(int(row["id"]))
                    continue
                try:
                    await channel.delete(reason=f"SentriX anti-nuke V55 : salon créé par le nuker {actor_id}")
                    result["channels_deleted"] += 1
                    handled_ids.add(int(row["id"]))
                except (discord.Forbidden, discord.HTTPException):
                    result["failed"] += 1
            elif row["action_type"] == "role_create":
                target_id = int(row["target_id"] or payload.get("id") or 0)
                role = guild.get_role(target_id)
                if role is None:
                    handled_ids.add(int(row["id"]))
                    continue
                if role.managed or role.is_default():
                    handled_ids.add(int(row["id"]))
                    continue
                try:
                    await role.delete(reason=f"SentriX anti-nuke V55 : rôle créé par le nuker {actor_id}")
                    result["roles_deleted"] += 1
                    handled_ids.add(int(row["id"]))
                except (discord.Forbidden, discord.HTTPException):
                    result["failed"] += 1

        role_deletes = [(row, payload) for row, payload in parsed if row["action_type"] == "role_delete"]
        role_deletes.sort(key=lambda item: int(item[1].get("position") or 0))
        for row, payload in role_deletes:
            if bool(payload.get("managed")):
                handled_ids.add(int(row["id"]))
                continue
            restored = await self._restore_role(guild, payload, role_map)
            if restored is not None:
                result["roles_restored"] += 1
                handled_ids.add(int(row["id"]))
            else:
                result["failed"] += 1

        channel_deletes = [(row, payload) for row, payload in parsed if row["action_type"] == "channel_delete"]
        channel_deletes.sort(
            key=lambda item: (
                0 if item[1].get("kind") == "category" else 1,
                int(item[1].get("position") or 0),
            )
        )
        for row, payload in channel_deletes:
            restored = await self._restore_deleted_channel(guild, payload, channel_map, role_map)
            if restored is not None:
                result["channels_restored"] += 1
                handled_ids.add(int(row["id"]))
            else:
                result["failed"] += 1

        for row, payload in reversed(parsed):
            if row["action_type"] == "role_update":
                if await self._restore_role_state(guild, payload, role_map):
                    result["roles_reverted"] += 1
                    handled_ids.add(int(row["id"]))
                else:
                    result["failed"] += 1
            elif row["action_type"] == "channel_update":
                if await self._restore_channel_state(guild, payload, channel_map, role_map):
                    result["channels_reverted"] += 1
                    handled_ids.add(int(row["id"]))
                else:
                    result["failed"] += 1

        if handled_ids:
            ids = sorted(handled_ids)
            placeholders = ",".join("?" for _ in ids)
            await self.bot.db.execute(
                f"UPDATE {_TABLE} SET handled = 1 WHERE id IN ({placeholders})",
                tuple(ids),
            )
        return result

    async def _reconcile_restored_channels(
        self,
        guild: discord.Guild,
        channel_map: dict[int, discord.abc.GuildChannel],
        role_map: dict[int, discord.Role],
        channel_snapshots: dict[int, dict[str, Any]],
    ) -> None:
        for old_id, snapshot in sorted(
            channel_snapshots.items(), key=lambda item: int(item[1].get("position") or 0)
        ):
            channel = channel_map.get(old_id)
            if channel is None:
                continue
            await self._restore_channel_state(guild, snapshot, channel_map, role_map)

    async def _send_summary(
        self,
        guild: discord.Guild,
        actor_id: int,
        reason: str,
        result: dict[str, int],
    ) -> None:
        automod = self.bot.get_cog("Automod")
        if automod is None:
            return
        key = (guild.id, int(actor_id))
        now = time.monotonic()
        if now - self._last_summary.get(key, 0.0) < PUNISH_COOLDOWN_SECONDS:
            return
        self._last_summary[key] = now
        try:
            e = embeds.log_entry(
                "ANTI-NUKE V55 — restauration terminée",
                discord.Color.orange(),
                cible=guild.get_member(actor_id) or actor_id,
                cible_label="Auteur détecté",
                raison=reason,
                extra={
                    "Salons recréés": str(result["channels_restored"]),
                    "Rôles recréés": str(result["roles_restored"]),
                    "Victimes débannies": str(result["unbanned"]),
                    "Salons malveillants retirés": str(result["channels_deleted"]),
                    "Rôles malveillants retirés": str(result["roles_deleted"]),
                    "Configurations restaurées": str(result["channels_reverted"] + result["roles_reverted"]),
                    "Échecs restant à retenter": str(result["failed"]),
                },
            )
            await automod.log_action(guild, e)
        except Exception:
            logger.exception("Anti-nuke V55: impossible d'envoyer le résumé de restauration.")

    async def restore_burst(self, guild: discord.Guild, actor_id: int, reason: str) -> dict[str, int]:
        key = (guild.id, int(actor_id))
        lock = self._restore_locks[key]
        async with lock:
            total = {
                "unbanned": 0,
                "channels_restored": 0,
                "channels_deleted": 0,
                "channels_reverted": 0,
                "roles_restored": 0,
                "roles_deleted": 0,
                "roles_reverted": 0,
                "failed": 0,
            }
            channel_map: dict[int, discord.abc.GuildChannel] = {}
            role_map: dict[int, discord.Role] = {}
            channel_snapshots: dict[int, dict[str, Any]] = {}

            for delay in RESTORE_DRAIN_DELAYS:
                await asyncio.sleep(delay)
                current = await self._rollback_once(
                    guild,
                    int(actor_id),
                    channel_map,
                    role_map,
                    channel_snapshots,
                )
                for field in total:
                    total[field] += int(current.get(field, 0))

            await self._reconcile_restored_channels(guild, channel_map, role_map, channel_snapshots)

            cutoff = int(time.time()) - DAMAGE_WINDOW_SECONDS
            try:
                row = await self.bot.db.fetchone(
                    f"SELECT COUNT(*) AS n FROM {_TABLE} "
                    "WHERE guild_id = ? AND actor_id = ? AND handled = 0 AND created_at >= ?",
                    (guild.id, int(actor_id), cutoff),
                )
                remaining = int(row["n"] if row else 0)
                total["failed"] = max(total["failed"], remaining)
            except Exception:
                pass

            await self._send_summary(guild, int(actor_id), reason, total)
            return total


def _patch_punishment(bot: commands.Bot) -> None:
    """Confinement d'abord, restauration ensuite, avec anti-doublon de rafale."""
    automod = bot.get_cog("Automod")
    if automod is None or getattr(automod, "_sentrix_punish_v55", False):
        return

    original_punish = automod.punish_nuker
    locks: dict[tuple[int, int], asyncio.Lock] = defaultdict(asyncio.Lock)
    last_punish: dict[tuple[int, int], float] = {}

    async def punish_v55(_self, guild: discord.Guild, actor_id: int, reason: str):
        key = (guild.id, int(actor_id))
        async with locks[key]:
            now = time.monotonic()
            if now - last_punish.get(key, 0.0) < PUNISH_COOLDOWN_SECONDS:
                return
            last_punish[key] = now

            member_before = guild.get_member(int(actor_id))
            await original_punish(guild, int(actor_id), reason)

            if member_before is None:
                try:
                    await guild.ban(
                        discord.Object(id=int(actor_id)),
                        reason=f"SentriX anti-nuke V55 : {reason}",
                        delete_message_seconds=3600,
                    )
                except (discord.Forbidden, discord.HTTPException):
                    logger.warning(
                        "Anti-nuke V55: impossible de bannir par ID l'auteur %s sur %s.",
                        actor_id,
                        guild.id,
                    )

            try:
                automod.nuke_tracker[(guild.id, int(actor_id))] = []
            except Exception:
                pass

            rollback = bot.get_cog(_COG_NAME)
            if rollback is not None:
                try:
                    await rollback.restore_burst(guild, int(actor_id), reason)
                except Exception:
                    logger.exception(
                        "Anti-nuke V55: restauration incomplète sur %s après confinement de %s.",
                        guild.id,
                        actor_id,
                    )

    automod.punish_nuker = MethodType(punish_v55, automod)
    automod._sentrix_punish_v55 = True
    logger.info("Anti-nuke V55: sanction avant rollback + anti-doublon activés.")


async def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_antinuke_emergency_v55", False):
        return
    automod = bot.get_cog("Automod")
    if automod is None:
        return

    await _ensure_table(bot)
    _patch_audit_actor(bot)
    if bot.get_cog(_COG_NAME) is None:
        await bot.add_cog(AntiNukeEmergencyV55(bot))
    _patch_punishment(bot)

    bot._sentrix_antinuke_emergency_v55 = True
    logger.info(
        "Anti-nuke V55 actif : audit robuste, auteur identifié, ban d'abord, restauration totale multi-passes."
    )
