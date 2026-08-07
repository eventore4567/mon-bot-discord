"""Journalisation complète des événements Discord.

Les salons sont ceux déjà enregistrés par +setup/+create-server dans guild_config :
log_messages, log_members, log_voice, log_roles, log_server, log_moderation et
log_automod. Le cog reste silencieux lorsqu'un salon n'est pas configuré ou inaccessible.

Les messages récents sont également conservés dans un cache SentriX persistant afin que
le journal puisse afficher leur contenu même lorsque Discord les a déjà retirés de son
cache interne au moment de la suppression.
"""

from __future__ import annotations

import json
import time

import discord
from discord.ext import commands

from utils import log_service


CONFIG_TO_LOG_TYPE = {
    "log_messages": "messages",
    "log_members": "members",
    "log_voice": "voice",
    "log_roles": "roles",
    "log_server": "server",
    "log_moderation": "moderation",
    "log_automod": "automod",
}

COLOURS = {
    "create": 0x57F287,
    "update": 0xFEE75C,
    "delete": 0xED4245,
    "member": 0x5865F2,
    "voice": 0x3498DB,
    "moderation": 0xEB459E,
}

MESSAGE_CACHE_RETENTION_SECONDS = 86400  # 24 h
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
    text = str(value) if value not in (None, "") else "Aucun"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _attachment_urls(message: discord.Message) -> list[str]:
    return [attachment.url for attachment in message.attachments]


class Logs(commands.Cog, name="Logs"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cache_writes = 0

    async def _send(self, guild: discord.Guild, config_key: str, embed: discord.Embed):
        """Envoyer chaque événement via la configuration de +logsetup."""
        log_type = CONFIG_TO_LOG_TYPE.get(config_key)
        if log_type is None:
            return
        await log_service.send_log(self.bot, guild, log_type, embed)

    @staticmethod
    def _embed(title: str, colour: int, *, target_id: int | None = None) -> discord.Embed:
        embed = discord.Embed(title=title, colour=colour, timestamp=discord.utils.utcnow())
        if target_id:
            embed.set_footer(text=f"Identifiant : {target_id}")
        else:
            embed.set_footer(text="SentriX • Journal du serveur")
        return embed

    async def _cache_message(self, message: discord.Message) -> None:
        """Mémorise un message avant qu'il puisse être supprimé du cache Discord."""
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
                    message.id,
                    message.guild.id,
                    message.channel.id,
                    message.author.id,
                    str(message.author),
                    message.content or "",
                    json.dumps(_attachment_urls(message), ensure_ascii=False),
                    int(time.time()),
                ),
            )
            self._cache_writes += 1
            if self._cache_writes % MESSAGE_CACHE_CLEANUP_EVERY == 0:
                await self.bot.db.execute(
                    "DELETE FROM message_log_cache WHERE stored_at < ?",
                    (int(time.time()) - MESSAGE_CACHE_RETENTION_SECONDS,),
                )
        except Exception:
            # Un problème de cache ne doit jamais empêcher les autres fonctions du bot.
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
            await self.bot.db.execute(
                "DELETE FROM message_log_cache WHERE message_id = ?",
                (message_id,),
            )
        except Exception:
            pass

    async def _log_deleted_from_row(
        self,
        guild: discord.Guild,
        row,
        *,
        fallback_channel_id: int | None = None,
    ) -> None:
        channel_id = int(row["channel_id"] or fallback_channel_id or 0)
        channel = guild.get_channel(channel_id) if channel_id else None
        author_id = int(row["author_id"])
        author_name = row["author_name"] or f"Utilisateur {author_id}"
        content = row["content"] or ""

        try:
            attachments = json.loads(row["attachments"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            attachments = []

        embed = self._embed("Message supprimé", COLOURS["delete"], target_id=int(row["message_id"]))
        embed.add_field(
            name="Auteur",
            value=f"<@{author_id}>\n`{author_name}`\n`ID: {author_id}`",
            inline=True,
        )
        embed.add_field(
            name="Salon",
            value=channel.mention if channel else f"`{channel_id}`",
            inline=True,
        )
        embed.add_field(
            name="Contenu",
            value=_short(content, 1024) if content else "*Aucun texte dans ce message.*",
            inline=False,
        )
        if attachments:
            embed.add_field(
                name="Pièces jointes",
                value=_short("\n".join(str(url) for url in attachments), 1024),
                inline=False,
            )
        await self._send(guild, "log_messages", embed)

    # ---------------- Messages ----------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        await self._cache_message(message)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.guild is None:
            return
        embed = self._embed("Message supprimé", COLOURS["delete"], target_id=message.id)
        embed.add_field(name="Auteur", value=f"{message.author.mention}\n`{message.author.id}`", inline=True)
        embed.add_field(name="Salon", value=message.channel.mention, inline=True)
        embed.add_field(
            name="Contenu",
            value=_short(message.content, 1024) if message.content else "*Aucun texte dans ce message.*",
            inline=False,
        )
        if message.attachments:
            embed.add_field(
                name="Pièces jointes",
                value=_short("\n".join(attachment.url for attachment in message.attachments), 1024),
                inline=False,
            )
        await self._send(message.guild, "log_messages", embed)
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
            await self._log_deleted_from_row(
                guild,
                row,
                fallback_channel_id=payload.channel_id,
            )
            await self._forget_cached_message(payload.message_id)
            return

        channel = guild.get_channel(payload.channel_id)
        embed = self._embed("Message supprimé", COLOURS["delete"], target_id=payload.message_id)
        embed.add_field(name="Salon", value=channel.mention if channel else f"`{payload.channel_id}`", inline=False)
        embed.description = (
            "Le contenu n'est pas disponible car SentriX n'avait pas vu ce message avant sa suppression "
            "(par exemple message envoyé avant le dernier redémarrage)."
        )
        await self._send(guild, "log_messages", embed)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent):
        if payload.guild_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        cached_ids = {message.id for message in payload.cached_messages}
        for message_id in payload.message_ids:
            # Les messages encore présents dans le cache Discord sont traités par
            # on_message_delete/on_bulk_message_delete selon discord.py ; on ne les double pas ici.
            if message_id in cached_ids:
                continue
            row = await self._cached_message_row(payload.guild_id, message_id)
            if row is None:
                continue
            await self._log_deleted_from_row(
                guild,
                row,
                fallback_channel_id=payload.channel_id,
            )
            await self._forget_cached_message(message_id)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.guild is not None:
            await self._cache_message(after)
        if before.guild is None or before.content == after.content:
            return
        embed = self._embed("Message modifié", COLOURS["update"], target_id=after.id)
        embed.add_field(name="Auteur", value=f"{after.author.mention}\n`{after.author.id}`", inline=True)
        embed.add_field(name="Salon", value=after.channel.mention, inline=True)
        embed.add_field(name="Avant", value=_short(before.content, 1024), inline=False)
        embed.add_field(name="Après", value=_short(after.content, 1024), inline=False)
        embed.add_field(name="Accès", value=f"[Voir le message]({after.jump_url})", inline=False)
        await self._send(after.guild, "log_messages", embed)

    # ---------------- Membres et rôles ----------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        embed = self._embed("Membre arrivé", COLOURS["create"], target_id=member.id)
        embed.description = member.mention
        embed.add_field(name="Compte créé", value=discord.utils.format_dt(member.created_at, "F"), inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        await self._send(member.guild, "log_members", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        embed = self._embed("Membre parti", COLOURS["delete"], target_id=member.id)
        embed.description = f"{member}"
        roles = [role.mention for role in member.roles[1:]]
        if roles:
            embed.add_field(name="Rôles", value=_short(", ".join(roles), 1024), inline=False)
        await self._send(member.guild, "log_members", embed)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.nick != after.nick:
            embed = self._embed("Surnom modifié", COLOURS["update"], target_id=after.id)
            embed.description = after.mention
            embed.add_field(name="Avant", value=_short(before.display_name), inline=True)
            embed.add_field(name="Après", value=_short(after.display_name), inline=True)
            await self._send(after.guild, "log_members", embed)

        before_roles = {role.id: role for role in before.roles[1:]}
        after_roles = {role.id: role for role in after.roles[1:]}
        added = [role for role_id, role in after_roles.items() if role_id not in before_roles]
        removed = [role for role_id, role in before_roles.items() if role_id not in after_roles]
        if added or removed:
            embed = self._embed("Rôles d'un membre modifiés", COLOURS["update"], target_id=after.id)
            embed.description = after.mention
            if added:
                embed.add_field(name="Ajoutés", value=_short(", ".join(role.mention for role in added), 1024), inline=False)
            if removed:
                embed.add_field(name="Retirés", value=_short(", ".join(role.mention for role in removed), 1024), inline=False)
            await self._send(after.guild, "log_roles", embed)

        if before.timed_out_until != after.timed_out_until:
            embed = self._embed("Timeout modifié", COLOURS["moderation"], target_id=after.id)
            embed.description = after.mention
            embed.add_field(
                name="Nouvel état",
                value=discord.utils.format_dt(after.timed_out_until, "F") if after.timed_out_until else "Timeout retiré",
                inline=False,
            )
            await self._send(after.guild, "log_moderation", embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User | discord.Member):
        embed = self._embed("Membre banni", COLOURS["moderation"], target_id=user.id)
        embed.description = f"{user}"
        await self._send(guild, "log_moderation", embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        embed = self._embed("Membre débanni", COLOURS["create"], target_id=user.id)
        embed.description = f"{user}"
        await self._send(guild, "log_moderation", embed)

    # ---------------- Vocaux ----------------

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if before.channel == after.channel and before.self_mute == after.self_mute and before.self_deaf == after.self_deaf:
            return
        embed = self._embed("Activité vocale", COLOURS["voice"], target_id=member.id)
        embed.description = member.mention
        if before.channel != after.channel:
            embed.add_field(name="Avant", value=before.channel.mention if before.channel else "Hors vocal", inline=True)
            embed.add_field(name="Après", value=after.channel.mention if after.channel else "Hors vocal", inline=True)
        if before.self_mute != after.self_mute:
            embed.add_field(name="Micro", value="Coupé" if after.self_mute else "Activé", inline=True)
        if before.self_deaf != after.self_deaf:
            embed.add_field(name="Casque", value="Désactivé" if after.self_deaf else "Activé", inline=True)
        await self._send(member.guild, "log_voice", embed)

    # ---------------- Serveur et rôles ----------------

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        embed = self._embed("Salon créé", COLOURS["create"], target_id=channel.id)
        embed.description = f"{channel.mention} — {channel.type}"
        await self._send(channel.guild, "log_server", embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        embed = self._embed("Salon supprimé", COLOURS["delete"], target_id=channel.id)
        embed.description = f"{channel.name} — {channel.type}"
        await self._send(channel.guild, "log_server", embed)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        changes = []
        if before.name != after.name:
            changes.append(f"Nom : `{before.name}` → `{after.name}`")
        if before.category_id != after.category_id:
            changes.append("Catégorie modifiée")
        if getattr(before, "topic", None) != getattr(after, "topic", None):
            changes.append("Sujet modifié")
        if not changes:
            return
        embed = self._embed("Salon modifié", COLOURS["update"], target_id=after.id)
        embed.description = _short("\n".join(changes), 4000)
        await self._send(after.guild, "log_server", embed)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        embed = self._embed("Rôle créé", COLOURS["create"], target_id=role.id)
        embed.description = role.mention
        await self._send(role.guild, "log_roles", embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        embed = self._embed("Rôle supprimé", COLOURS["delete"], target_id=role.id)
        embed.description = role.name
        await self._send(role.guild, "log_roles", embed)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        changes = []
        if before.name != after.name:
            changes.append(f"Nom : `{before.name}` → `{after.name}`")
        if before.colour != after.colour:
            changes.append(f"Couleur : `{before.colour}` → `{after.colour}`")
        if before.permissions != after.permissions:
            changes.append("Permissions modifiées")
        if before.position != after.position:
            changes.append(f"Position : `{before.position}` → `{after.position}`")
        if not changes:
            return
        embed = self._embed("Rôle modifié", COLOURS["update"], target_id=after.id)
        embed.description = after.mention + "\n" + _short("\n".join(changes), 3900)
        await self._send(after.guild, "log_roles", embed)

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        changes = []
        if before.name != after.name:
            changes.append(f"Nom : `{before.name}` → `{after.name}`")
        if before.icon != after.icon:
            changes.append("Icône modifiée")
        if before.banner != after.banner:
            changes.append("Bannière modifiée")
        if before.verification_level != after.verification_level:
            changes.append(f"Vérification : `{before.verification_level}` → `{after.verification_level}`")
        if not changes:
            return
        embed = self._embed("Serveur modifié", COLOURS["update"], target_id=after.id)
        embed.description = _short("\n".join(changes), 4000)
        await self._send(after, "log_server", embed)


async def setup(bot: commands.Bot):
    await bot.db.execute(MESSAGE_CACHE_SCHEMA)
    await bot.db.execute(
        "CREATE INDEX IF NOT EXISTS idx_message_log_cache_stored_at ON message_log_cache(stored_at)"
    )
    await bot.db.execute(
        "DELETE FROM message_log_cache WHERE stored_at < ?",
        (int(time.time()) - MESSAGE_CACHE_RETENTION_SECONDS,),
    )
    await bot.add_cog(Logs(bot))
