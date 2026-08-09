"""Rollback défensif anti-nuke pour SentriX.

Ce module complète le moteur anti-nuke existant sans remplacer sa détection :
- mémorise les bannissements effectués par un même acteur ;
- mémorise les salons supprimés, créés ou modifiés ;
- quand AutoMod déclenche réellement l'anti-nuke, restaure les dégâts récents AVANT
  d'appliquer la sanction déjà prévue par AutoMod ;
- les victimes de bannissements massifs sont débannies ;
- les salons supprimés sont recréés au mieux avec catégorie, position et permissions ;
- les salons créés en masse par le nuker sont supprimés ;
- les renommages/permissions de salons sont restaurés lorsque possible.

Le journal est persistant en SQLite afin qu'un redémarrage au mauvais moment ne fasse pas
perdre la liste des dégâts à réparer. Les entrées expirent rapidement et ne contiennent
que des IDs Discord et la configuration minimale nécessaire à la restauration.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from types import MethodType

import discord
from discord.ext import commands

from utils import embeds

logger = logging.getLogger("bot.antinuke.rollback")
_COG_NAME = "AntiNukeRollback"
ROLLBACK_WINDOW = 45
MAX_ROLLBACK_ROWS = 80


async def _ensure_table(bot: commands.Bot) -> None:
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
    await bot.db.execute(
        "CREATE INDEX IF NOT EXISTS idx_antinuke_rollback_actor "
        "ON antinuke_rollback_actions (guild_id, actor_id, handled, created_at)"
    )


def _permission_overwrites_snapshot(channel: discord.abc.GuildChannel) -> list[dict]:
    result: list[dict] = []
    try:
        items = channel.overwrites.items()
    except Exception:
        return result
    for target, overwrite in items:
        try:
            allow, deny = overwrite.pair()
            result.append(
                {
                    "id": int(target.id),
                    "type": "role" if isinstance(target, discord.Role) else "member",
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


def _channel_snapshot(channel: discord.abc.GuildChannel) -> dict:
    data: dict = {
        "id": int(channel.id),
        "kind": _channel_kind(channel),
        "name": channel.name,
        "position": int(getattr(channel, "position", 0) or 0),
        "category_id": int(channel.category_id) if getattr(channel, "category_id", None) else None,
        "overwrites": _permission_overwrites_snapshot(channel),
    }

    if isinstance(channel, discord.CategoryChannel):
        data["child_ids"] = [int(child.id) for child in channel.channels]
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
    return data


def _update_snapshot(before: discord.abc.GuildChannel) -> dict:
    """État suffisant pour annuler un renommage ou une modification de permissions."""
    return {
        "id": int(before.id),
        "name": before.name,
        "position": int(getattr(before, "position", 0) or 0),
        "category_id": int(before.category_id) if getattr(before, "category_id", None) else None,
        "overwrites": _permission_overwrites_snapshot(before),
        "topic": getattr(before, "topic", None),
        "nsfw": getattr(before, "nsfw", None),
        "slowmode_delay": getattr(before, "slowmode_delay", None),
        "bitrate": getattr(before, "bitrate", None),
        "user_limit": getattr(before, "user_limit", None),
    }


class AntiNukeRollback(commands.Cog, name=_COG_NAME):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._rollback_locks: dict[tuple[int, int], asyncio.Lock] = defaultdict(asyncio.Lock)

    async def _antinuke_context(
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
        payload: dict | None = None,
    ) -> None:
        now_ts = int(time.time())
        try:
            await self.bot.db.execute(
                "DELETE FROM antinuke_rollback_actions WHERE created_at < ? OR handled = 1",
                (now_ts - 300,),
            )
            await self.bot.db.execute(
                "INSERT INTO antinuke_rollback_actions "
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
            logger.exception("Impossible d'enregistrer un dégât anti-nuke sur %s.", guild.id)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        _automod, actor = await self._antinuke_context(
            guild, discord.AuditLogAction.ban, user.id
        )
        if actor is None:
            return
        await self._record(guild, actor.id, "ban", user.id, {"user_id": int(user.id)})

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        _automod, actor = await self._antinuke_context(
            channel.guild, discord.AuditLogAction.channel_delete, channel.id
        )
        if actor is None:
            return
        await self._record(
            channel.guild,
            actor.id,
            "channel_delete",
            channel.id,
            _channel_snapshot(channel),
        )

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        _automod, actor = await self._antinuke_context(
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
        # L'AutoMod historique compte déjà les renommages. Ici on journalise l'état avant
        # modification. Si seules les permissions changent, on les compte aussi afin qu'un
        # attaquant ne puisse pas rendre tous les salons publics/privés sans être détecté.
        name_changed = before.name != after.name
        overwrites_changed = before.overwrites != after.overwrites
        if not name_changed and not overwrites_changed:
            return

        automod, actor = await self._antinuke_context(
            after.guild, discord.AuditLogAction.channel_update, after.id
        )
        if actor is None:
            return
        await self._record(
            after.guild,
            actor.id,
            "channel_update",
            after.id,
            _update_snapshot(before),
        )

        # Évite le double comptage d'un renommage : automod.py le compte déjà.
        if overwrites_changed and not name_changed:
            try:
                if await automod.record_nuke_action(after.guild, actor.id):
                    await automod.punish_nuker(
                        after.guild,
                        actor.id,
                        "Modification massive des permissions de salons",
                    )
            except Exception:
                logger.exception("Échec du déclenchement anti-nuke sur permissions de salons.")

    def _restore_overwrites(self, guild: discord.Guild, raw: list[dict] | None) -> dict:
        overwrites: dict = {}
        for item in raw or []:
            try:
                target_id = int(item["id"])
                if item.get("type") == "role":
                    target = guild.get_role(target_id)
                else:
                    target = guild.get_member(target_id)
                if target is None:
                    continue
                allow = discord.Permissions(permissions=int(item.get("allow", 0)))
                deny = discord.Permissions(permissions=int(item.get("deny", 0)))
                overwrites[target] = discord.PermissionOverwrite.from_pair(allow, deny)
            except Exception:
                continue
        return overwrites

    async def _restore_deleted_channel(
        self,
        guild: discord.Guild,
        snapshot: dict,
        restored_ids: dict[int, discord.abc.GuildChannel],
    ) -> discord.abc.GuildChannel | None:
        old_id = int(snapshot.get("id") or 0)
        if old_id and guild.get_channel(old_id) is not None:
            return guild.get_channel(old_id)

        name = str(snapshot.get("name") or "salon-restaure")[:100]
        kind = snapshot.get("kind") or "text"
        overwrites = self._restore_overwrites(guild, snapshot.get("overwrites"))
        position = max(0, int(snapshot.get("position") or 0))
        reason = "SentriX anti-nuke : restauration automatique d'un salon supprimé"

        category = None
        old_category_id = snapshot.get("category_id")
        if old_category_id:
            mapped = restored_ids.get(int(old_category_id))
            if isinstance(mapped, discord.CategoryChannel):
                category = mapped
            else:
                existing = guild.get_channel(int(old_category_id))
                if isinstance(existing, discord.CategoryChannel):
                    category = existing

        try:
            if kind == "category":
                created = await guild.create_category(
                    name,
                    overwrites=overwrites,
                    position=position,
                    reason=reason,
                )
            elif kind == "voice":
                created = await guild.create_voice_channel(
                    name,
                    category=category,
                    overwrites=overwrites,
                    position=position,
                    bitrate=int(snapshot.get("bitrate") or 64000),
                    user_limit=int(snapshot.get("user_limit") or 0),
                    nsfw=bool(snapshot.get("nsfw") or False),
                    reason=reason,
                )
            elif kind == "stage":
                created = await guild.create_stage_channel(
                    name,
                    category=category,
                    overwrites=overwrites,
                    position=position,
                    bitrate=int(snapshot.get("bitrate") or 64000),
                    user_limit=int(snapshot.get("user_limit") or 0),
                    nsfw=bool(snapshot.get("nsfw") or False),
                    reason=reason,
                )
            elif kind == "forum" and hasattr(guild, "create_forum_channel"):
                created = await guild.create_forum_channel(
                    name,
                    category=category,
                    overwrites=overwrites,
                    position=position,
                    topic=snapshot.get("topic"),
                    nsfw=bool(snapshot.get("nsfw") or False),
                    slowmode_delay=int(snapshot.get("slowmode_delay") or 0),
                    reason=reason,
                )
            else:
                created = await guild.create_text_channel(
                    name,
                    category=category,
                    overwrites=overwrites,
                    position=position,
                    topic=snapshot.get("topic"),
                    nsfw=bool(snapshot.get("nsfw") or False),
                    slowmode_delay=int(snapshot.get("slowmode_delay") or 0),
                    default_auto_archive_duration=int(snapshot.get("default_auto_archive_duration") or 1440),
                    default_thread_slowmode_delay=int(snapshot.get("default_thread_slowmode_delay") or 0),
                    news=(kind == "news"),
                    reason=reason,
                )
        except (discord.Forbidden, discord.HTTPException, TypeError, ValueError):
            logger.exception(
                "Impossible de recréer le salon %s (%s) sur %s.",
                name,
                old_id,
                guild.id,
            )
            return None

        if old_id:
            restored_ids[old_id] = created

        # Si c'était une catégorie supprimée, les salons enfants qui existent encore sont
        # replacés dedans. Les enfants eux-mêmes supprimés seront recréés ensuite grâce au map.
        if kind == "category":
            for child_id in snapshot.get("child_ids") or []:
                child = guild.get_channel(int(child_id))
                if child is not None and not isinstance(child, discord.CategoryChannel):
                    try:
                        await child.edit(category=created, reason=reason)
                    except (discord.Forbidden, discord.HTTPException):
                        pass
        return created

    async def _restore_channel_update(
        self,
        guild: discord.Guild,
        snapshot: dict,
        restored_ids: dict[int, discord.abc.GuildChannel],
    ) -> bool:
        old_id = int(snapshot.get("id") or 0)
        channel = guild.get_channel(old_id) or restored_ids.get(old_id)
        if channel is None:
            return False

        reason = "SentriX anti-nuke : annulation d'une modification massive de salon"
        kwargs: dict = {
            "name": str(snapshot.get("name") or channel.name)[:100],
            "overwrites": self._restore_overwrites(guild, snapshot.get("overwrites")),
            "position": max(0, int(snapshot.get("position") or 0)),
            "reason": reason,
        }
        old_category_id = snapshot.get("category_id")
        if not isinstance(channel, discord.CategoryChannel):
            category = None
            if old_category_id:
                mapped = restored_ids.get(int(old_category_id))
                if isinstance(mapped, discord.CategoryChannel):
                    category = mapped
                else:
                    existing = guild.get_channel(int(old_category_id))
                    if isinstance(existing, discord.CategoryChannel):
                        category = existing
            kwargs["category"] = category

        # Les attributs ci-dessous ne sont pas acceptés par tous les types de salons.
        if isinstance(channel, discord.TextChannel):
            kwargs["topic"] = snapshot.get("topic")
            kwargs["nsfw"] = bool(snapshot.get("nsfw") or False)
            kwargs["slowmode_delay"] = int(snapshot.get("slowmode_delay") or 0)
        elif isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            if snapshot.get("bitrate") is not None:
                kwargs["bitrate"] = int(snapshot["bitrate"])
            if snapshot.get("user_limit") is not None:
                kwargs["user_limit"] = int(snapshot["user_limit"])
            if snapshot.get("nsfw") is not None:
                kwargs["nsfw"] = bool(snapshot["nsfw"])

        try:
            await channel.edit(**kwargs)
            return True
        except (discord.Forbidden, discord.HTTPException, TypeError, ValueError):
            logger.exception("Impossible de restaurer la configuration du salon %s.", old_id)
            return False

    async def rollback_actor(self, guild: discord.Guild, actor_id: int, reason: str) -> dict:
        """Répare tous les dégâts récents attribués à l'acteur qui vient de déclencher l'anti-nuke."""
        lock = self._rollback_locks[(guild.id, int(actor_id))]
        async with lock:
            # Les listeners Discord sont dispatchés en tâches concurrentes. Cette courte pause
            # laisse le temps au listener du dernier événement d'écrire son snapshot avant que
            # punish_nuker() lise le journal.
            await asyncio.sleep(0.35)
            cutoff = int(time.time()) - ROLLBACK_WINDOW
            rows = await self.bot.db.fetchall(
                "SELECT * FROM antinuke_rollback_actions "
                "WHERE guild_id = ? AND actor_id = ? AND handled = 0 AND created_at >= ? "
                "ORDER BY id DESC LIMIT ?",
                (guild.id, int(actor_id), cutoff, MAX_ROLLBACK_ROWS),
            )
            if not rows:
                return {"unbanned": 0, "restored": 0, "deleted": 0, "reverted": 0}

            parsed: list[tuple] = []
            for row in rows:
                try:
                    payload = json.loads(row["payload_json"] or "{}")
                except (TypeError, ValueError):
                    payload = {}
                parsed.append((row, payload))

            result = {"unbanned": 0, "restored": 0, "deleted": 0, "reverted": 0}
            restored_ids: dict[int, discord.abc.GuildChannel] = {}

            # 1. Débannit d'abord toutes les victimes bannies par l'acteur dans la rafale.
            seen_users: set[int] = set()
            for row, payload in parsed:
                if row["action_type"] != "ban":
                    continue
                target_id = int(row["target_id"] or payload.get("user_id") or 0)
                if not target_id or target_id in seen_users or target_id == actor_id:
                    continue
                seen_users.add(target_id)
                try:
                    await guild.unban(
                        discord.Object(id=target_id),
                        reason=f"SentriX anti-nuke : annulation d'un bannissement massif par {actor_id}",
                    )
                    result["unbanned"] += 1
                except discord.NotFound:
                    pass
                except (discord.Forbidden, discord.HTTPException):
                    logger.exception("Impossible de débannir automatiquement %s sur %s.", target_id, guild.id)

            # 2. Supprime les salons que l'attaquant vient de créer en masse.
            for row, payload in parsed:
                if row["action_type"] != "channel_create":
                    continue
                target_id = int(row["target_id"] or payload.get("id") or 0)
                channel = guild.get_channel(target_id)
                if channel is None:
                    continue
                try:
                    await channel.delete(reason=f"SentriX anti-nuke : suppression d'un salon créé en masse par {actor_id}")
                    result["deleted"] += 1
                except (discord.Forbidden, discord.HTTPException):
                    logger.exception("Impossible de retirer le salon créé en masse %s.", target_id)

            # 3. Recrée les catégories supprimées avant les salons qui en dépendaient.
            delete_rows = [(row, payload) for row, payload in parsed if row["action_type"] == "channel_delete"]
            delete_rows.sort(key=lambda item: 0 if item[1].get("kind") == "category" else 1)
            for _row, payload in delete_rows:
                restored = await self._restore_deleted_channel(guild, payload, restored_ids)
                if restored is not None:
                    result["restored"] += 1

            # 4. Rejoue les états "before" du plus récent vers le plus ancien : si un salon
            # a été renommé plusieurs fois, on revient ainsi jusqu'au nom/configuration initiale.
            for row, payload in parsed:
                if row["action_type"] != "channel_update":
                    continue
                if await self._restore_channel_update(guild, payload, restored_ids):
                    result["reverted"] += 1

            ids = [int(row["id"]) for row, _payload in parsed]
            placeholders = ",".join("?" for _ in ids)
            if ids:
                await self.bot.db.execute(
                    f"UPDATE antinuke_rollback_actions SET handled = 1 WHERE id IN ({placeholders})",
                    tuple(ids),
                )

            automod = self.bot.get_cog("Automod")
            if automod is not None:
                try:
                    e = embeds.log_entry(
                        "🧯 ANTI-NUKE — restauration automatique",
                        discord.Color.orange(),
                        cible=guild.get_member(actor_id) or actor_id,
                        cible_label="Auteur détecté",
                        raison=reason,
                        extra={
                            "Membres débannis": str(result["unbanned"]),
                            "Salons recréés": str(result["restored"]),
                            "Salons malveillants supprimés": str(result["deleted"]),
                            "Salons restaurés": str(result["reverted"]),
                        },
                    )
                    await automod.log_action(guild, e)
                except Exception:
                    logger.exception("Impossible d'envoyer le résumé de restauration anti-nuke.")
            return result


def _patch_punishment(bot: commands.Bot) -> None:
    """Fait exécuter le rollback juste avant la sanction anti-nuke déjà existante."""
    automod = bot.get_cog("Automod")
    if automod is None or getattr(automod, "_sentrix_rollback_patched", False):
        return

    original_punish = automod.punish_nuker

    async def punish_with_rollback(_self, guild: discord.Guild, actor_id: int, reason: str):
        rollback = bot.get_cog(_COG_NAME)
        if rollback is not None:
            try:
                await rollback.rollback_actor(guild, actor_id, reason)
            except Exception:
                # Une restauration partielle ne doit JAMAIS empêcher la sanction du nuker.
                logger.exception("Rollback anti-nuke incomplet sur %s ; sanction maintenue.", guild.id)
        return await original_punish(guild, actor_id, reason)

    automod.punish_nuker = MethodType(punish_with_rollback, automod)
    automod._sentrix_rollback_patched = True
    logger.info("Rollback anti-nuke branché avant punish_nuker().")


async def install(bot: commands.Bot) -> None:
    await _ensure_table(bot)
    if bot.get_cog(_COG_NAME) is None:
        await bot.add_cog(AntiNukeRollback(bot))
        logger.info("Journal et restauration anti-nuke chargés.")
    _patch_punishment(bot)
