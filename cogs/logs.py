"""Listeners Discord officiels des journaux SentriX.

Chaque événement est normalisé ici puis envoyé exclusivement par utils.log_service.
Le renderer officiel est utils.embeds. Aucun listener de ce cog n'envoie directement
un message dans un salon de logs.
"""
from __future__ import annotations

import json
import time
from datetime import timedelta

import discord
from discord.ext import commands

from utils import embeds, log_service

CONFIG_TO_LOG_TYPE = {
    "log_messages": "messages",
    "log_members": "members",
    "log_voice": "voice",
    "log_roles": "roles",
    "log_server": "server",
    "log_moderation": "moderation",
    "log_automod": "automod",
}

MESSAGE_CACHE_RETENTION_SECONDS = 86400
MESSAGE_CACHE_CLEANUP_EVERY = 250
MESSAGE_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS message_log_cache (
    message_id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    author_name TEXT NOT NULL,
    content TEXT,
    attachments TEXT NOT NULL DEFAULT '[]',
    stored_at INTEGER NOT NULL
)
"""


def _short(value: object, limit: int = 1000) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _attachment_urls(message: discord.Message) -> list[str]:
    return [attachment.url for attachment in message.attachments]


def _user_ref(user_id: int) -> str:
    return f"<@{int(user_id)}>"


def _role_ref(role_id: int) -> str:
    return f"<@&{int(role_id)}>"


def _channel_ref(channel_id: int) -> str:
    return f"<#{int(channel_id)}>"


class Logs(commands.Cog, name="Logs"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cache_writes = 0

    async def _send(
        self,
        guild: discord.Guild,
        config_key: str,
        embed: discord.Embed,
        *,
        view: discord.ui.View | None = None,
        event_key: str | None = None,
    ) -> None:
        log_type = CONFIG_TO_LOG_TYPE.get(config_key)
        if log_type is None:
            return
        await log_service.send_log(self.bot, guild, log_type, embed, view=view, event_key=event_key)

    @staticmethod
    def _embed(
        title: str,
        *,
        identity=None,
        fields=(),
        description: str = "",
    ) -> discord.Embed:
        avatar = None
        identity_text = ""
        if identity is not None:
            identity_id = getattr(identity, "id", None)
            identity_name = getattr(identity, "display_name", None) or getattr(identity, "name", None) or str(identity)
            if identity_id:
                identity_text = f"**{identity_name}**\nID : `{identity_id}`"
            else:
                identity_text = f"**{identity_name}**"
            asset = getattr(identity, "display_avatar", None)
            if asset is not None:
                avatar = str(asset.url)
        body = identity_text
        if description:
            body = f"{body}\n\n{description}" if body else description
        panel = embeds.log_embed(title, fields=fields, description=body)
        if avatar:
            panel.set_thumbnail(url=avatar)
        return panel

    async def _audit_actor(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        target_id: int,
        *,
        max_age_seconds: int = 8,
    ) -> tuple[discord.abc.User | None, discord.AuditLogEntry | None]:
        """Corrèle action+cible+temps. Ne prend jamais simplement « la dernière entrée »."""
        if guild.me is None or not guild.me.guild_permissions.view_audit_log:
            return None, None
        now = discord.utils.utcnow()
        try:
            async for entry in guild.audit_logs(limit=8, action=action):
                entry_target = getattr(entry.target, "id", None)
                if entry_target != target_id:
                    continue
                created = entry.created_at
                if abs((now - created).total_seconds()) > max_age_seconds:
                    continue
                return entry.user, entry
        except (discord.Forbidden, discord.HTTPException):
            pass
        return None, None

    async def _cache_message(self, message: discord.Message) -> None:
        if message.guild is None:
            return
        try:
            await self.bot.db.execute(
                """
                INSERT INTO message_log_cache
                    (message_id, guild_id, channel_id, author_id, author_name, content, attachments, stored_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    guild_id = excluded.guild_id,
                    channel_id = excluded.channel_id,
                    author_id = excluded.author_id,
                    author_name = excluded.author_name,
                    content = excluded.content,
                    attachments = excluded.attachments,
                    stored_at = excluded.stored_at
                """,
                (
                    message.id, message.guild.id, message.channel.id, message.author.id,
                    str(message.author), message.content or "",
                    json.dumps(_attachment_urls(message), ensure_ascii=False), int(time.time()),
                ),
            )
            self._cache_writes += 1
            if self._cache_writes % MESSAGE_CACHE_CLEANUP_EVERY == 0:
                await self.bot.db.execute(
                    "DELETE FROM message_log_cache WHERE stored_at < ?",
                    (int(time.time()) - MESSAGE_CACHE_RETENTION_SECONDS,),
                )
        except Exception:
            return

    async def _cached_message_row(self, guild_id: int, message_id: int):
        try:
            return await self.bot.db.fetchone(
                "SELECT * FROM message_log_cache WHERE guild_id = ? AND message_id = ?",
                (guild_id, message_id),
            )
        except Exception:
            return None

    async def _forget_cached_message(self, message_id: int) -> None:
        try:
            await self.bot.db.execute("DELETE FROM message_log_cache WHERE message_id = ?", (message_id,))
        except Exception:
            pass

    async def _log_deleted_from_row(self, guild: discord.Guild, row, *, fallback_channel_id: int | None = None) -> None:
        message_id = int(row["message_id"])
        channel_id = int(row["channel_id"] or fallback_channel_id or 0)
        author_id = int(row["author_id"])
        content = row["content"] or ""
        try:
            attachments = json.loads(row["attachments"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            attachments = []
        fields = [
            ("Auteur", _user_ref(author_id), True),
            ("Salon", _channel_ref(channel_id) if channel_id else None, True),
            ("Contenu", _short(content, 1024) if content else None, False),
            ("Pièces jointes", _short("\n".join(map(str, attachments)), 1024) if attachments else None, False),
        ]
        member = guild.get_member(author_id)
        panel = self._embed("Message supprimé", identity=member, fields=fields)
        view = log_service.log_actions(ids=[("Copier l'ID de l'auteur", author_id), ("Copier l'ID du message", message_id)])
        key = log_service.make_event_key(guild.id, "message_delete", target_id=author_id, message_id=message_id)
        await self._send(guild, "log_messages", panel, view=view, event_key=key)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        await self._cache_message(message)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.guild is None:
            return
        fields = [
            ("Auteur", _user_ref(message.author.id), True),
            ("Salon", _channel_ref(message.channel.id), True),
            ("Contenu", _short(message.content, 1024) if message.content else None, False),
            ("Pièces jointes", _short("\n".join(a.url for a in message.attachments), 1024) if message.attachments else None, False),
        ]
        panel = self._embed("Message supprimé", identity=message.author, fields=fields)
        view = log_service.log_actions(ids=[("Copier l'ID de l'auteur", message.author.id), ("Copier l'ID du message", message.id)])
        key = log_service.make_event_key(message.guild.id, "message_delete", target_id=message.author.id, message_id=message.id)
        await self._send(message.guild, "log_messages", panel, view=view, event_key=key)
        await self._forget_cached_message(message.id)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if payload.guild_id is None or payload.cached_message is not None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        row = await self._cached_message_row(payload.guild_id, payload.message_id)
        if row is not None:
            await self._log_deleted_from_row(guild, row, fallback_channel_id=payload.channel_id)
            await self._forget_cached_message(payload.message_id)
            return
        panel = self._embed(
            "Message supprimé",
            fields=(("Salon", _channel_ref(payload.channel_id), True),),
            description="Le contenu n’était pas disponible dans le cache SentriX.",
        )
        view = log_service.log_actions(ids=[("Copier l'ID du message", payload.message_id)])
        key = log_service.make_event_key(guild.id, "message_delete", message_id=payload.message_id)
        await self._send(guild, "log_messages", panel, view=view, event_key=key)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent):
        if payload.guild_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        for message_id in payload.message_ids:
            row = await self._cached_message_row(payload.guild_id, message_id)
            if row is not None:
                await self._log_deleted_from_row(guild, row, fallback_channel_id=payload.channel_id)
                await self._forget_cached_message(message_id)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.guild is not None:
            await self._cache_message(after)
        if before.guild is None or before.content == after.content:
            return
        panel = self._embed(
            "Message modifié",
            identity=after.author,
            fields=(
                ("Auteur", _user_ref(after.author.id), True),
                ("Salon", _channel_ref(after.channel.id), True),
                ("Avant", _short(before.content, 1024), False),
                ("Après", _short(after.content, 1024), False),
            ),
        )
        view = log_service.log_actions(
            jump_url=after.jump_url,
            ids=[("Copier l'ID de l'auteur", after.author.id), ("Copier l'ID du message", after.id)],
        )
        key = log_service.make_event_key(after.guild.id, "message_edit", target_id=after.author.id, message_id=after.id, discriminator=after.edited_at.timestamp() if after.edited_at else time.time_ns())
        await self._send(after.guild, "log_messages", panel, view=view, event_key=key)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        panel = self._embed(
            "Membre arrivé",
            identity=member,
            fields=(
                ("Membre", _user_ref(member.id), True),
                ("Compte créé", discord.utils.format_dt(member.created_at, "F"), True),
                ("Arrivée", discord.utils.format_dt(member.joined_at or discord.utils.utcnow(), "F"), True),
            ),
        )
        view = log_service.log_actions(ids=[("Copier l'ID du membre", member.id)])
        key = log_service.make_event_key(member.guild.id, "member_join", target_id=member.id)
        await self._send(member.guild, "log_members", panel, view=view, event_key=key)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        fields = [("Membre", _user_ref(member.id), True)]
        if member.joined_at:
            duration = discord.utils.utcnow() - member.joined_at
            fields.append(("Présence", f"{max(0, duration.days)} jour(s)", True))
        panel = self._embed("Membre parti", identity=member, fields=fields)
        view = log_service.log_actions(ids=[("Copier l'ID du membre", member.id)])
        key = log_service.make_event_key(member.guild.id, "member_remove", target_id=member.id)
        await self._send(member.guild, "log_members", panel, view=view, event_key=key)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.nick != after.nick:
            actor, audit = await self._audit_actor(after.guild, discord.AuditLogAction.member_update, after.id)
            fields = [("Membre", _user_ref(after.id), True), ("Avant", before.display_name, True), ("Après", after.display_name, True)]
            if actor:
                fields.append(("Responsable", _user_ref(actor.id), True))
            panel = self._embed("Surnom modifié", identity=after, fields=fields)
            key = log_service.make_event_key(after.guild.id, "nickname_update", target_id=after.id, executor_id=getattr(actor, "id", None), audit_log_id=getattr(audit, "id", None), discriminator=after.display_name)
            await self._send(after.guild, "log_members", panel, event_key=key)

        before_roles = {role.id: role for role in before.roles[1:]}
        after_roles = {role.id: role for role in after.roles[1:]}
        added = [role for role_id, role in after_roles.items() if role_id not in before_roles]
        removed = [role for role_id, role in before_roles.items() if role_id not in after_roles]
        actor, audit = (None, None)
        if added or removed:
            actor, audit = await self._audit_actor(after.guild, discord.AuditLogAction.member_role_update, after.id)
        for role in added:
            fields = [("Membre", _user_ref(after.id), True), ("Rôle", _role_ref(role.id), True)]
            if actor:
                fields.append(("Modérateur", _user_ref(actor.id), True))
            panel = self._embed("Rôle ajouté", identity=after, fields=fields)
            ids = [("Copier l'ID du membre", after.id), ("Copier l'ID du rôle", role.id)]
            if actor:
                ids.append(("Copier l'ID du modérateur", actor.id))
            view = log_service.log_actions(ids=ids)
            key = log_service.make_event_key(after.guild.id, "role_add", target_id=after.id, executor_id=getattr(actor, "id", None), audit_log_id=getattr(audit, "id", None), discriminator=role.id)
            await self._send(after.guild, "log_roles", panel, view=view, event_key=key)
        for role in removed:
            fields = [("Membre", _user_ref(after.id), True), ("Rôle", _role_ref(role.id), True)]
            if actor:
                fields.append(("Modérateur", _user_ref(actor.id), True))
            panel = self._embed("Rôle retiré", identity=after, fields=fields)
            ids = [("Copier l'ID du membre", after.id), ("Copier l'ID du rôle", role.id)]
            if actor:
                ids.append(("Copier l'ID du modérateur", actor.id))
            view = log_service.log_actions(ids=ids)
            key = log_service.make_event_key(after.guild.id, "role_remove", target_id=after.id, executor_id=getattr(actor, "id", None), audit_log_id=getattr(audit, "id", None), discriminator=role.id)
            await self._send(after.guild, "log_roles", panel, view=view, event_key=key)

        if before.timed_out_until != after.timed_out_until:
            actor, audit = await self._audit_actor(after.guild, discord.AuditLogAction.member_update, after.id)
            fields = [("Membre", _user_ref(after.id), True)]
            if actor:
                fields.append(("Modérateur", _user_ref(actor.id), True))
            if after.timed_out_until:
                fields.append(("Fin prévue", discord.utils.format_dt(after.timed_out_until, "F"), True))
            panel = self._embed("Timeout appliqué" if after.timed_out_until else "Timeout retiré", identity=after, fields=fields)
            ids = [("Copier l'ID du membre", after.id)]
            if actor:
                ids.append(("Copier l'ID du modérateur", actor.id))
            view = log_service.log_actions(ids=ids)
            key = log_service.make_event_key(after.guild.id, "timeout_update", target_id=after.id, executor_id=getattr(actor, "id", None), audit_log_id=getattr(audit, "id", None), discriminator=int(after.timed_out_until.timestamp()) if after.timed_out_until else 0)
            await self._send(after.guild, "log_moderation", panel, view=view, event_key=key)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User | discord.Member):
        actor, audit = await self._audit_actor(guild, discord.AuditLogAction.ban, user.id)
        fields = [("Membre", _user_ref(user.id), True)]
        if actor:
            fields.append(("Modérateur", _user_ref(actor.id), True))
        reason = getattr(audit, "reason", None)
        if reason:
            fields.append(("Raison", _short(reason, 1024), False))
        panel = self._embed("Membre banni", identity=user, fields=fields)
        ids = [("Copier l'ID du membre", user.id)]
        if actor:
            ids.append(("Copier l'ID du modérateur", actor.id))
        view = log_service.log_actions(ids=ids)
        key = log_service.make_event_key(guild.id, "ban", target_id=user.id, executor_id=getattr(actor, "id", None), audit_log_id=getattr(audit, "id", None))
        await self._send(guild, "log_moderation", panel, view=view, event_key=key)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        actor, audit = await self._audit_actor(guild, discord.AuditLogAction.unban, user.id)
        fields = [("Utilisateur", _user_ref(user.id), True)]
        if actor:
            fields.append(("Modérateur", _user_ref(actor.id), True))
        reason = getattr(audit, "reason", None)
        if reason:
            fields.append(("Raison", _short(reason, 1024), False))
        panel = self._embed("Membre débanni", identity=user, fields=fields)
        ids = [("Copier l'ID du membre", user.id)]
        if actor:
            ids.append(("Copier l'ID du modérateur", actor.id))
        view = log_service.log_actions(ids=ids)
        key = log_service.make_event_key(guild.id, "unban", target_id=user.id, executor_id=getattr(actor, "id", None), audit_log_id=getattr(audit, "id", None))
        await self._send(guild, "log_moderation", panel, view=view, event_key=key)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if before.channel == after.channel and before.self_mute == after.self_mute and before.self_deaf == after.self_deaf:
            return
        fields = [("Membre", _user_ref(member.id), True)]
        if before.channel != after.channel:
            fields.extend((("Avant", _channel_ref(before.channel.id) if before.channel else "Hors vocal", True), ("Après", _channel_ref(after.channel.id) if after.channel else "Hors vocal", True)))
        if before.self_mute != after.self_mute:
            fields.append(("Micro", "Coupé" if after.self_mute else "Activé", True))
        if before.self_deaf != after.self_deaf:
            fields.append(("Casque", "Désactivé" if after.self_deaf else "Activé", True))
        panel = self._embed("Activité vocale", identity=member, fields=fields)
        key = log_service.make_event_key(member.guild.id, "voice", target_id=member.id, discriminator=f"{getattr(after.channel, 'id', 0)}:{after.self_mute}:{after.self_deaf}")
        await self._send(member.guild, "log_voice", panel, event_key=key)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        actor, audit = await self._audit_actor(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        fields = [("Salon", _channel_ref(channel.id), True), ("Type", str(channel.type), True)]
        if actor:
            fields.append(("Responsable", _user_ref(actor.id), True))
        panel = self._embed("Salon créé", fields=fields)
        ids = [("Copier l'ID du salon", channel.id)] + ([("Copier l'ID du responsable", actor.id)] if actor else [])
        view = log_service.log_actions(ids=ids)
        key = log_service.make_event_key(channel.guild.id, "channel_create", target_id=channel.id, executor_id=getattr(actor, "id", None), audit_log_id=getattr(audit, "id", None))
        await self._send(channel.guild, "log_server", panel, view=view, event_key=key)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        actor, audit = await self._audit_actor(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        fields = [("Salon", f"`{channel.name}`", True), ("ID", f"`{channel.id}`", True)]
        if actor:
            fields.append(("Responsable", _user_ref(actor.id), True))
        panel = self._embed("Salon supprimé", fields=fields)
        ids = [("Copier l'ID du salon", channel.id)] + ([("Copier l'ID du responsable", actor.id)] if actor else [])
        view = log_service.log_actions(ids=ids)
        key = log_service.make_event_key(channel.guild.id, "channel_delete", target_id=channel.id, executor_id=getattr(actor, "id", None), audit_log_id=getattr(audit, "id", None))
        await self._send(channel.guild, "log_server", panel, view=view, event_key=key)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        fields = [("Salon", _channel_ref(after.id), True)]
        if before.name != after.name:
            fields.append(("Nom", f"`{before.name}` → `{after.name}`", False))
        if before.category_id != after.category_id:
            fields.append(("Catégorie", f"`{before.category_id or 'Aucune'}` → `{after.category_id or 'Aucune'}`", False))
        if getattr(before, "topic", None) != getattr(after, "topic", None):
            fields.append(("Sujet", f"`{_short(getattr(before, 'topic', ''), 400)}` → `{_short(getattr(after, 'topic', ''), 400)}`", False))
        if getattr(before, "slowmode_delay", None) != getattr(after, "slowmode_delay", None):
            fields.append(("Slowmode", f"`{getattr(before, 'slowmode_delay', 0)} s` → `{getattr(after, 'slowmode_delay', 0)} s`", False))
        if len(fields) == 1:
            return
        actor, audit = await self._audit_actor(after.guild, discord.AuditLogAction.channel_update, after.id)
        if actor:
            fields.append(("Responsable", _user_ref(actor.id), True))
        panel = self._embed("Salon modifié", fields=fields)
        view = log_service.log_actions(ids=[("Copier l'ID du salon", after.id)] + ([("Copier l'ID du responsable", actor.id)] if actor else []))
        key = log_service.make_event_key(after.guild.id, "channel_update", target_id=after.id, executor_id=getattr(actor, "id", None), audit_log_id=getattr(audit, "id", None), discriminator=hash(tuple(str(x) for x in fields)))
        await self._send(after.guild, "log_server", panel, view=view, event_key=key)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        actor, audit = await self._audit_actor(role.guild, discord.AuditLogAction.role_create, role.id)
        fields = [("Rôle", _role_ref(role.id), True)]
        if actor:
            fields.append(("Responsable", _user_ref(actor.id), True))
        panel = self._embed("Rôle créé", fields=fields)
        view = log_service.log_actions(ids=[("Copier l'ID du rôle", role.id)] + ([("Copier l'ID du responsable", actor.id)] if actor else []))
        key = log_service.make_event_key(role.guild.id, "role_create", target_id=role.id, executor_id=getattr(actor, "id", None), audit_log_id=getattr(audit, "id", None))
        await self._send(role.guild, "log_roles", panel, view=view, event_key=key)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        actor, audit = await self._audit_actor(role.guild, discord.AuditLogAction.role_delete, role.id)
        fields = [("Rôle", f"`{role.name}`", True), ("ID", f"`{role.id}`", True)]
        if actor:
            fields.append(("Responsable", _user_ref(actor.id), True))
        panel = self._embed("Rôle supprimé", fields=fields)
        view = log_service.log_actions(ids=[("Copier l'ID du rôle", role.id)] + ([("Copier l'ID du responsable", actor.id)] if actor else []))
        key = log_service.make_event_key(role.guild.id, "role_delete", target_id=role.id, executor_id=getattr(actor, "id", None), audit_log_id=getattr(audit, "id", None))
        await self._send(role.guild, "log_roles", panel, view=view, event_key=key)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        fields = [("Rôle", _role_ref(after.id), True)]
        if before.name != after.name:
            fields.append(("Nom", f"`{before.name}` → `{after.name}`", False))
        if before.colour != after.colour:
            fields.append(("Couleur", f"`{before.colour}` → `{after.colour}`", False))
        if before.permissions != after.permissions:
            added = [name for name, value in after.permissions if value and not getattr(before.permissions, name)]
            removed = [name for name, value in before.permissions if value and not getattr(after.permissions, name)]
            if added:
                fields.append(("Permissions ajoutées", _short(", ".join(added), 1024), False))
            if removed:
                fields.append(("Permissions supprimées", _short(", ".join(removed), 1024), False))
        if len(fields) == 1:
            return
        actor, audit = await self._audit_actor(after.guild, discord.AuditLogAction.role_update, after.id)
        if actor:
            fields.append(("Responsable", _user_ref(actor.id), True))
        panel = self._embed("Rôle modifié", fields=fields)
        view = log_service.log_actions(ids=[("Copier l'ID du rôle", after.id)] + ([("Copier l'ID du responsable", actor.id)] if actor else []))
        key = log_service.make_event_key(after.guild.id, "role_update", target_id=after.id, executor_id=getattr(actor, "id", None), audit_log_id=getattr(audit, "id", None), discriminator=hash(tuple(str(x) for x in fields)))
        await self._send(after.guild, "log_roles", panel, view=view, event_key=key)

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        fields = []
        if before.name != after.name:
            fields.append(("Nom", f"`{before.name}` → `{after.name}`", False))
        if before.icon != after.icon:
            fields.append(("Icône", "Modifiée", True))
        if before.banner != after.banner:
            fields.append(("Bannière", "Modifiée", True))
        if before.verification_level != after.verification_level:
            fields.append(("Vérification", f"`{before.verification_level}` → `{after.verification_level}`", False))
        if not fields:
            return
        actor, audit = await self._audit_actor(after, discord.AuditLogAction.guild_update, after.id)
        if actor:
            fields.append(("Responsable", _user_ref(actor.id), True))
        panel = self._embed("Serveur modifié", fields=fields)
        key = log_service.make_event_key(after.id, "guild_update", target_id=after.id, executor_id=getattr(actor, "id", None), audit_log_id=getattr(audit, "id", None), discriminator=hash(tuple(str(x) for x in fields)))
        await self._send(after, "log_server", panel, event_key=key)


async def setup(bot: commands.Bot):
    await bot.db.execute(MESSAGE_CACHE_SCHEMA)
    await bot.db.execute("CREATE INDEX IF NOT EXISTS idx_message_log_cache_stored_at ON message_log_cache(stored_at)")
    await bot.db.execute("DELETE FROM message_log_cache WHERE stored_at < ?", (int(time.time()) - MESSAGE_CACHE_RETENTION_SECONDS,))
    await bot.add_cog(Logs(bot))
