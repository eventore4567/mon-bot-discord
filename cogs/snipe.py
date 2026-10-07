"""Snipe temporaire pour la modération SentriX.

Le module garde uniquement une petite fenêtre en mémoire :
- dernier message supprimé par salon ;
- dernière modification par salon ;
- métadonnées des pièces jointes quand Discord les fournit.

Aucune donnée de snipe n'est persistée en base et tout disparaît au redémarrage.
Les suppressions issues de +clear sont volontairement ignorées.
"""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
import os
import time

import discord
from discord.ext import commands

from utils import embeds, log_service
from utils import sentrix_panels as panels


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


SNIPE_RETENTION_SECONDS = _env_int(
    "SENTRIX_SNIPE_RETENTION_SECONDS", 600, 60, 3600
)
SNIPE_MESSAGE_CACHE_LIMIT = _env_int(
    "SENTRIX_SNIPE_MESSAGE_CACHE_LIMIT", 6000, 500, 20000
)
SNIPE_HISTORY_PER_CHANNEL = _env_int(
    "SENTRIX_SNIPE_HISTORY_PER_CHANNEL", 5, 1, 20
)

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif")


@dataclass(frozen=True, slots=True)
class AttachmentSnapshot:
    filename: str
    url: str
    proxy_url: str
    content_type: str
    size: int

    @property
    def best_url(self) -> str:
        return self.proxy_url or self.url

    @property
    def is_image(self) -> bool:
        content_type = self.content_type.casefold()
        if content_type.startswith("image/"):
            return True
        return self.filename.casefold().endswith(_IMAGE_EXTENSIONS)


@dataclass(frozen=True, slots=True)
class MessageSnapshot:
    message_id: int
    guild_id: int
    channel_id: int
    author_id: int
    author_name: str
    author_avatar: str
    content: str
    attachments: tuple[AttachmentSnapshot, ...]
    created_at: int
    jump_url: str


@dataclass(frozen=True, slots=True)
class DeletedEntry:
    message: MessageSnapshot
    event_at: int
    recorded_at: float


@dataclass(frozen=True, slots=True)
class EditEntry:
    before: MessageSnapshot
    after: MessageSnapshot
    event_at: int
    recorded_at: float


def _clip(value: object, limit: int = 1000) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _literal_content(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "Aucun texte"
    text = discord.utils.escape_mentions(text)
    text = discord.utils.escape_markdown(text)
    return _clip(text, 1000)


def _human_size(size: int) -> str:
    value = max(0, int(size or 0))
    if value < 1024:
        return f"{value} o"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} Ko"
    return f"{value / (1024 * 1024):.1f} Mo"


class Snipe(commands.Cog):
    """Historique très court des suppressions et modifications de messages."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._messages: OrderedDict[int, tuple[float, MessageSnapshot]] = OrderedDict()
        self._deleted: dict[int, deque[DeletedEntry]] = {}
        self._edited: dict[int, deque[EditEntry]] = {}
        self._deleted_ids: OrderedDict[int, float] = OrderedDict()

    def cog_unload(self) -> None:
        self._messages.clear()
        self._deleted.clear()
        self._edited.clear()
        self._deleted_ids.clear()

    @staticmethod
    def _attachments(message: discord.Message) -> tuple[AttachmentSnapshot, ...]:
        items: list[AttachmentSnapshot] = []
        for attachment in list(getattr(message, "attachments", ()) or ())[:10]:
            items.append(
                AttachmentSnapshot(
                    filename=_clip(getattr(attachment, "filename", "fichier"), 120),
                    url=str(getattr(attachment, "url", "") or ""),
                    proxy_url=str(getattr(attachment, "proxy_url", "") or ""),
                    content_type=str(getattr(attachment, "content_type", "") or ""),
                    size=int(getattr(attachment, "size", 0) or 0),
                )
            )
        return tuple(items)

    @classmethod
    def _snapshot(cls, message: discord.Message) -> MessageSnapshot | None:
        if message.guild is None or getattr(message.author, "bot", False):
            return None
        avatar = getattr(getattr(message.author, "display_avatar", None), "url", "")
        created_at = getattr(message, "created_at", None)
        return MessageSnapshot(
            message_id=int(message.id),
            guild_id=int(message.guild.id),
            channel_id=int(message.channel.id),
            author_id=int(message.author.id),
            author_name=_clip(
                getattr(message.author, "display_name", None)
                or getattr(message.author, "name", None)
                or str(message.author),
                100,
            ),
            author_avatar=str(avatar or ""),
            content=str(message.content or ""),
            attachments=cls._attachments(message),
            created_at=int(created_at.timestamp()) if created_at is not None else int(time.time()),
            jump_url=str(getattr(message, "jump_url", "") or ""),
        )

    def _prune(self) -> None:
        now = time.monotonic()
        cutoff = now - SNIPE_RETENTION_SECONDS

        while self._messages:
            _message_id, (stored_at, _snapshot) = next(iter(self._messages.items()))
            if stored_at >= cutoff:
                break
            self._messages.popitem(last=False)

        while self._deleted_ids:
            _message_id, stored_at = next(iter(self._deleted_ids.items()))
            if stored_at >= cutoff:
                break
            self._deleted_ids.popitem(last=False)

        for storage in (self._deleted, self._edited):
            for channel_id, entries in list(storage.items()):
                while entries and entries[0].recorded_at < cutoff:
                    entries.popleft()
                if not entries:
                    storage.pop(channel_id, None)

    def _remember_message(self, snapshot: MessageSnapshot) -> None:
        self._prune()
        now = time.monotonic()
        self._messages[snapshot.message_id] = (now, snapshot)
        self._messages.move_to_end(snapshot.message_id)
        while len(self._messages) > SNIPE_MESSAGE_CACHE_LIMIT:
            self._messages.popitem(last=False)

    def _take_cached_message(self, message_id: int) -> MessageSnapshot | None:
        self._prune()
        item = self._messages.pop(int(message_id), None)
        return item[1] if item is not None else None

    def _record_deleted(self, snapshot: MessageSnapshot) -> None:
        self._prune()
        if snapshot.message_id in self._deleted_ids:
            return
        now = time.monotonic()
        self._deleted_ids[snapshot.message_id] = now
        self._deleted_ids.move_to_end(snapshot.message_id)
        entries = self._deleted.setdefault(
            snapshot.channel_id,
            deque(maxlen=SNIPE_HISTORY_PER_CHANNEL),
        )
        entries.append(
            DeletedEntry(
                message=snapshot,
                event_at=int(time.time()),
                recorded_at=now,
            )
        )

    def _record_edit(self, before: MessageSnapshot, after: MessageSnapshot) -> None:
        self._prune()
        entries = self._edited.setdefault(
            after.channel_id,
            deque(maxlen=SNIPE_HISTORY_PER_CHANNEL),
        )
        entries.append(
            EditEntry(
                before=before,
                after=after,
                event_at=int(time.time()),
                recorded_at=time.monotonic(),
            )
        )

    @staticmethod
    def _channel_allowed(ctx: commands.Context, channel) -> bool:
        if ctx.guild is None or channel is None:
            return False
        if int(getattr(channel, "guild", ctx.guild).id) != int(ctx.guild.id):
            return False
        permissions_for = getattr(channel, "permissions_for", None)
        if not callable(permissions_for):
            return False
        permissions = permissions_for(ctx.author)
        return bool(
            getattr(permissions, "view_channel", False)
            and getattr(permissions, "read_message_history", False)
        )

    @staticmethod
    def _attachment_summary(attachments: tuple[AttachmentSnapshot, ...]) -> str:
        if not attachments:
            return ""
        lines = []
        for item in attachments[:5]:
            lines.append(f"{item.filename} · {_human_size(item.size)}")
        if len(attachments) > 5:
            lines.append(f"+{len(attachments) - 5} autre(s) fichier(s)")
        return _clip("\n".join(lines), 1000)

    @staticmethod
    def _buttons(
        snapshot: MessageSnapshot,
        *,
        include_message: bool,
    ) -> list[panels.Bouton]:
        buttons: list[panels.Bouton] = []
        if include_message and snapshot.jump_url:
            buttons.append(panels.Bouton("Voir le message", url=snapshot.jump_url))
        else:
            buttons.append(
                panels.Bouton(
                    "Accéder au salon",
                    url=(
                        f"https://discord.com/channels/"
                        f"{snapshot.guild_id}/{snapshot.channel_id}"
                    ),
                )
            )

        remaining = 5 - len(buttons)
        for index, attachment in enumerate(snapshot.attachments[:remaining], start=1):
            url = attachment.best_url
            if not url:
                continue
            if attachment.is_image:
                label = "Ouvrir l'image" if index == 1 else f"Image {index}"
            else:
                label = "Ouvrir le fichier" if index == 1 else f"Fichier {index}"
            buttons.append(panels.Bouton(label, url=url))
        return buttons

    @staticmethod
    async def _short_reply(ctx: commands.Context, text: str) -> None:
        await ctx.send(
            text,
            ephemeral=ctx.interaction is not None,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _target_channel(
        self,
        ctx: commands.Context,
        salon: discord.TextChannel | None,
    ):
        if ctx.guild is None:
            await self._short_reply(ctx, "Cette commande fonctionne uniquement sur un serveur.")
            return None
        channel = salon or ctx.channel
        if not self._channel_allowed(ctx, channel):
            await self._short_reply(
                ctx,
                "Tu dois pouvoir voir l'historique du salon pour utiliser le snipe ici.",
            )
            return None
        return channel

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        snapshot = self._snapshot(message)
        if snapshot is not None:
            self._remember_message(snapshot)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        before_snapshot = self._snapshot(before)
        after_snapshot = self._snapshot(after)
        if after_snapshot is not None:
            self._remember_message(after_snapshot)
        if before_snapshot is None or after_snapshot is None:
            return
        if (
            before_snapshot.content == after_snapshot.content
            and before_snapshot.attachments == after_snapshot.attachments
        ):
            return
        self._record_edit(before_snapshot, after_snapshot)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        snapshot = self._snapshot(message)
        self._messages.pop(int(message.id), None)
        if snapshot is None or log_service.is_purged(message.id):
            return
        self._record_deleted(snapshot)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if payload.guild_id is None:
            return
        if log_service.is_purged(payload.message_id):
            self._messages.pop(int(payload.message_id), None)
            return

        snapshot = None
        cached_message = getattr(payload, "cached_message", None)
        if cached_message is not None:
            snapshot = self._snapshot(cached_message)
        if snapshot is None:
            snapshot = self._take_cached_message(payload.message_id)
        else:
            self._messages.pop(int(payload.message_id), None)

        if snapshot is not None:
            self._record_deleted(snapshot)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent):
        if payload.guild_id is None:
            return
        cached = {
            int(message.id): message
            for message in (getattr(payload, "cached_messages", None) or ())
        }
        for message_id in payload.message_ids:
            message_id = int(message_id)
            if log_service.is_purged(message_id):
                self._messages.pop(message_id, None)
                continue
            message = cached.get(message_id)
            snapshot = self._snapshot(message) if message is not None else None
            if snapshot is None:
                snapshot = self._take_cached_message(message_id)
            else:
                self._messages.pop(message_id, None)
            if snapshot is not None:
                self._record_deleted(snapshot)

    @commands.hybrid_command(
        name="snipe",
        description="Afficher le dernier message supprimé récemment dans un salon.",
    )
    async def snipe(
        self,
        ctx: commands.Context,
        salon: discord.TextChannel | None = None,
    ):
        channel = await self._target_channel(ctx, salon)
        if channel is None:
            return

        self._prune()
        entries = self._deleted.get(int(channel.id))
        if not entries:
            return await self._short_reply(
                ctx,
                "Aucun message supprimé récent n'est disponible dans ce salon.",
            )

        entry = entries[-1]
        message = entry.message
        panel = embeds.standard(
            "Message supprimé",
            f"Dernier message supprimé récemment dans <#{message.channel_id}>.",
            thumbnail=message.author_avatar or None,
            timestamp=False,
        )
        embeds.add_fields(
            panel,
            (
                ("Auteur", f"{message.author_name}\nID : {message.author_id}", True),
                ("Supprimé", f"<t:{entry.event_at}:R>", True),
                ("Contenu", _literal_content(message.content), False),
                (
                    "Pièces jointes",
                    self._attachment_summary(message.attachments) or None,
                    False,
                ),
            ),
        )
        first_image = next(
            (item.best_url for item in message.attachments if item.is_image and item.best_url),
            None,
        )
        if first_image:
            panel.set_image(url=first_image)

        panneau = panels.depuis_embed(
            panel,
            kind="info",
            boutons=self._buttons(message, include_message=False),
        )
        await panels.envoyer(
            ctx,
            panneau,
            ephemere=ctx.interaction is not None,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.hybrid_command(
        name="editsnipe",
        aliases=("esnipe",),
        description="Afficher la dernière modification récente d'un message.",
    )
    async def editsnipe(
        self,
        ctx: commands.Context,
        salon: discord.TextChannel | None = None,
    ):
        channel = await self._target_channel(ctx, salon)
        if channel is None:
            return

        self._prune()
        entries = self._edited.get(int(channel.id))
        if not entries:
            return await self._short_reply(
                ctx,
                "Aucune modification récente n'est disponible dans ce salon.",
            )

        entry = entries[-1]
        before = entry.before
        after = entry.after
        panel = embeds.standard(
            "Message modifié",
            f"Dernière modification récente dans <#{after.channel_id}>.",
            thumbnail=after.author_avatar or before.author_avatar or None,
            timestamp=False,
        )
        embeds.add_fields(
            panel,
            (
                ("Auteur", f"{after.author_name}\nID : {after.author_id}", True),
                ("Modifié", f"<t:{entry.event_at}:R>", True),
                ("Avant", _literal_content(before.content), False),
                ("Après", _literal_content(after.content), False),
                (
                    "Pièces jointes",
                    self._attachment_summary(after.attachments) or None,
                    False,
                ),
            ),
        )
        first_image = next(
            (item.best_url for item in after.attachments if item.is_image and item.best_url),
            None,
        )
        if first_image:
            panel.set_image(url=first_image)

        panneau = panels.depuis_embed(
            panel,
            kind="info",
            boutons=self._buttons(after, include_message=True),
        )
        await panels.envoyer(
            ctx,
            panneau,
            ephemere=ctx.interaction is not None,
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Snipe(bot))
