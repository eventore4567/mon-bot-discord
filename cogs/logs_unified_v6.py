"""V6 finale des journaux SentriX.

Cette couche ne remplace pas le transport V5.3 (validé en production). Elle normalise
uniquement les producteurs et la structure :
- une barre large commune à tous les logs ;
- références de salons lisibles même après suppression ;
- logs de fichiers/images supprimés dans logs-dossiers ;
- tickets centralisés dans logs-tickets avec transcript téléchargeable par bouton ;
- +reset-logs-all étendu à 9 routes officielles et synchronisation des types de ticket.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import time
import types
from typing import Any

import discord
from discord.ext import commands

from utils import embeds, log_compact_final, log_service
from utils import sentrix_panels as panels
from . import generated_logs_sync
from . import log_transport_v52
from . import logs as logs_mod
from . import owner_log_rebuild as rebuild_v1
from . import owner_log_rebuild_v2 as rebuild_v2

logger = logging.getLogger("bot.logs-unified-v6")

# Un cran plus long que la barre précédente, partagé commandes + logs.
LOG_BAR = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
FILES_ROUTE = (
    "files",
    "log_files",
    "logs-dossiers",
    "Images, fichiers et pièces jointes supprimés.",
)
FILES_META = {
    "label": "Fichiers supprimés (images et pièces jointes)",
    "category": "Fichiers",
    "legacy_column": "log_files",
    "emits": True,
}
TRANSCRIPT_SCHEMA = """
CREATE TABLE IF NOT EXISTS ticket_transcripts (
    ticket_id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    channel_name TEXT NOT NULL,
    transcript_text TEXT NOT NULL,
    created_at INTEGER NOT NULL
)
"""

LEGACY_LOG_NAMES = {
    "logs-message", "logs-messages", "logs-membre", "logs-membres",
    "logs-role", "logs-roles", "logs-serveur", "logs-server", "logs-salons",
    "logs-vocal", "logs-vocaux", "logs-moderation", "logs-modération",
    "logs-automod", "logs-securite", "logs-sécurité", "automod", "automod-logs",
    "raidprotect-logs", "anti-raid-logs", "logs-protect-spam-logs",
    "logs-ticket", "logs-tickets", "logs-files", "logs-fichiers", "logs-dossiers",
}

_CHANNEL_NAMES: dict[int, str] = {}
_BOT: commands.Bot | None = None
_PATCHED_RESET = False
_PATCHED_TICKETS = False
_PATCHED_RAW_FILES = False


def _clean_channel_name(name: object) -> str:
    value = str(name or "").strip().lstrip("#")
    return value[:100] or "salon-supprime"


def _remember_channel(channel: discord.abc.GuildChannel | None) -> None:
    if channel is None:
        return
    channel_id = getattr(channel, "id", None)
    name = getattr(channel, "name", None)
    if channel_id and name:
        _CHANNEL_NAMES[int(channel_id)] = _clean_channel_name(name)


def _channel_ref_v6(channel_id: int) -> str:
    """Mention native tant que le salon existe + nom persistant en secours.

    Une mention <#id> devient « #inconnu » après suppression côté client Discord. Le nom
    textuel est donc volontairement conservé à côté : l'ancien log reste lisible ensuite.
    """
    try:
        value = int(channel_id)
    except (TypeError, ValueError):
        return "`Salon indisponible`"

    channel = _BOT.get_channel(value) if _BOT is not None else None
    if isinstance(channel, discord.abc.GuildChannel):
        _remember_channel(channel)
        return f"{channel.mention} • `#{_clean_channel_name(channel.name)}`"

    known = _CHANNEL_NAMES.get(value)
    if known:
        return f"`#{known}`"
    return f"`ID {value}`"


def _channel_value(channel: discord.abc.GuildChannel | None) -> str:
    if channel is None:
        return "`Salon indisponible`"
    _remember_channel(channel)
    return _channel_ref_v6(channel.id)


def _route_marker(topic: str) -> str:
    return f"SentriX logs • {topic}"


async def _ensure_schema(bot: commands.Bot) -> None:
    """Ajoute la route legacy log_files sans imposer une recréation de la SQLite."""
    try:
        rows = await bot.db.fetchall("PRAGMA table_info(guild_config)")
        names = set()
        for row in rows or []:
            try:
                names.add(str(row["name"]))
            except (KeyError, TypeError, IndexError):
                try:
                    names.add(str(row[1]))
                except Exception:
                    pass
        if "log_files" not in names:
            await bot.db.execute("ALTER TABLE guild_config ADD COLUMN log_files INTEGER")
    except Exception as exc:
        # Deux instances peuvent tenter l'ALTER simultanément : duplicate column est sain.
        if "duplicate column" not in str(exc).casefold():
            logger.exception("V6 : migration log_files impossible.")
            raise

    await bot.db.execute(TRANSCRIPT_SCHEMA)


def _install_routes() -> None:
    log_service.LOG_TYPES["files"] = dict(FILES_META)
    if "Fichiers" not in log_service.CATEGORY_ORDER:
        try:
            index = log_service.CATEGORY_ORDER.index("Messages") + 1
        except ValueError:
            index = 0
        log_service.CATEGORY_ORDER.insert(index, "Fichiers")

    if not any(route[0] == "files" for route in rebuild_v1.LOG_ROUTES):
        rebuild_v1.LOG_ROUTES = tuple(rebuild_v1.LOG_ROUTES) + (FILES_ROUTE,)
    rebuild_v1.KNOWN_OLD_LOG_NAMES.update(LEGACY_LOG_NAMES)
    rebuild_v1.LEGACY_COLUMNS = tuple(route[1] for route in rebuild_v1.LOG_ROUTES) + ("log_channel",)

    # cogs.logs n'a plus de table CONFIG_TO_LOG_TYPE : chaque listener passe son type
    # d'événement canonique. La route "files" est alimentée par UnifiedLogsV6 lui-même.
    # Les alias de la route Fichiers sont declares dans generated_logs_sync, table
    # canonique. Ils etaient auparavant reecrits ici au runtime, via un nom de dictionnaire
    # qui n'existait pas (_NORMALIZED_ALIASES au lieu de _NORMALIZED) : l'AttributeError
    # faisait echouer logs_unified_v6.install() et, avec lui, tout le chargement de
    # slash_error_completion_guard, donc no_cooldown_final et passive_ai_single_reply_final.
    assert "files" in generated_logs_sync.LOG_CHANNEL_ALIASES


def _install_visuals(bot: commands.Bot) -> None:
    global _BOT
    _BOT = bot
    embeds.BAR = LOG_BAR
    log_compact_final.PANEL_BAR = LOG_BAR
    logs_mod._channel_ref = _channel_ref_v6
    for guild in list(bot.guilds):
        for channel in list(guild.channels):
            _remember_channel(channel)


async def _current_route_ids(bot: commands.Bot, guild: discord.Guild) -> set[int]:
    result: set[int] = set()
    for log_type, _column, _name, _topic in rebuild_v1.LOG_ROUTES:
        try:
            setting = await log_service.get_log_setting(bot, guild.id, log_type)
            channel_id = int(setting.get("channel_id") or 0)
        except Exception:
            channel_id = 0
        if channel_id:
            result.add(channel_id)
    return result


async def _cleanup_obsolete_sentrix_logs(bot: commands.Bot, guild: discord.Guild) -> int:
    """Supprime seulement les anciens salons identifiables SentriX, jamais moderator-only."""
    current_ids = await _current_route_ids(bot, guild)
    deleted = 0
    for channel in list(guild.text_channels):
        if channel.id in current_ids:
            continue
        name = channel.name.casefold()
        if name not in LEGACY_LOG_NAMES:
            continue
        topic = (channel.topic or "").casefold()
        category_name = (channel.category.name if channel.category else "").casefold()
        sentrix_owned = (
            ("sentrix" in topic and "log" in topic)
            or ("sentrix" in category_name and "log" in category_name)
        )
        if not sentrix_owned:
            continue
        try:
            await channel.delete(reason="Nettoyage ancienne architecture logs SentriX V6")
            deleted += 1
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
    return deleted


def _patch_reset_v2() -> None:
    global _PATCHED_RESET
    if _PATCHED_RESET:
        return
    current = rebuild_v2.OwnerLogRebuildV2._rebuild_one_guild
    if getattr(current, "_sentrix_unified_v6", False):
        _PATCHED_RESET = True
        return

    async def rebuild_v6(self, guild: discord.Guild, requester: discord.abc.User):
        result = await current(self, guild, requester)
        if not result.ok:
            return result
        try:
            ticket_setting = await log_service.get_log_setting(self.bot, guild.id, "tickets")
            ticket_channel_id = int(ticket_setting.get("channel_id") or 0)
            if ticket_channel_id:
                # Après reset, TOUS les types de tickets utilisent le salon officiel.
                await self.bot.db.execute(
                    "UPDATE ticket_types SET log_channel_id = ? WHERE guild_id = ?",
                    (ticket_channel_id, guild.id),
                )
            result.deleted += await _cleanup_obsolete_sentrix_logs(self.bot, guild)
        except Exception:
            logger.exception("V6 : post-synchronisation du reset impossible guild=%s", guild.id)
        return result

    rebuild_v6._sentrix_unified_v6 = True
    rebuild_v6._sentrix_original = current
    rebuild_v2.OwnerLogRebuildV2._rebuild_one_guild = rebuild_v6
    _PATCHED_RESET = True


def _attachment_line(attachment: discord.Attachment) -> str:
    size = int(getattr(attachment, "size", 0) or 0)
    if size >= 1024 * 1024:
        size_text = f"{size / (1024 * 1024):.1f} Mo"
    elif size >= 1024:
        size_text = f"{size / 1024:.1f} Ko"
    else:
        size_text = f"{size} o"
    kind = str(getattr(attachment, "content_type", None) or "fichier")
    return f"**{attachment.filename}** • {size_text} • `{kind}`"


async def _best_effort_files(attachments: list[discord.Attachment]) -> list[discord.File]:
    files: list[discord.File] = []
    for attachment in attachments[:10]:
        try:
            files.append(await attachment.to_file(use_cached=True))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, OSError):
            continue
    return files


async def _send_files_log(
    bot: commands.Bot,
    guild: discord.Guild,
    panel: discord.Embed,
    *,
    files: list[discord.File] | None = None,
    view: discord.ui.View | None = None,
    event_key: str | None = None,
) -> bool:
    """Même transport natif que V5.3, avec prise en charge de plusieurs fichiers."""
    files = list(files or [])[:10]
    try:
        setting, _recovered = await log_transport_v52._resolve_setting(
            bot, guild, "files", needs_file=bool(files)
        )
        if setting is None:
            return False
        channel_id = int(setting.get("channel_id") or 0)
        valid, _reason = log_service.validate_channel(
            guild, channel_id, needs_file=bool(files)
        )
        if not valid:
            return False
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return False

        rendered = log_transport_v52._render(panel)
        semantic_key = log_service.semantic_event_key(guild.id, "files", rendered)
        if log_service._is_duplicate(event_key) or log_service._is_duplicate(semantic_key):
            return False

        if files:
            first_image = next(
                (
                    attachment
                    for attachment, file in zip([], files)
                    if False
                ),
                None,
            )
            del first_image

        kwargs: dict[str, Any] = {
            "embed": rendered,
            "allowed_mentions": log_service.LOG_ALLOWED_MENTIONS,
        }
        if view is not None:
            kwargs["view"] = view
        if files:
            kwargs["files"] = files
        native_send = log_transport_v52._unwrap_messageable_send()
        await native_send(channel, **kwargs)
        return True
    except Exception:
        logger.exception("V6 : envoi logs-dossiers impossible guild=%s", guild.id)
        return False


async def _store_transcript(
    bot: commands.Bot,
    *,
    ticket_id: int,
    guild_id: int,
    channel_id: int,
    channel_name: str,
    text: str,
) -> None:
    await bot.db.execute(
        "INSERT INTO ticket_transcripts "
        "(ticket_id, guild_id, channel_id, channel_name, transcript_text, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(ticket_id) DO UPDATE SET "
        "guild_id=excluded.guild_id, channel_id=excluded.channel_id, "
        "channel_name=excluded.channel_name, transcript_text=excluded.transcript_text, "
        "created_at=excluded.created_at",
        (ticket_id, guild_id, channel_id, channel_name, text, int(time.time())),
    )


def _ticket_actions(
    *,
    ticket_id: int,
    channel_id: int,
    opener_id: int | None,
    closer_id: int | None,
) -> discord.ui.View:
    ids: list[tuple[str, int]] = [("Copier l'ID du salon", channel_id)]
    if opener_id:
        ids.append(("Copier l'ID du membre", opener_id))
    if closer_id and closer_id != opener_id:
        ids.append(("Copier l'ID du responsable", closer_id))
    view = log_service.log_actions(ids=ids) or discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            label="Télécharger la transcript",
            style=discord.ButtonStyle.secondary,
            custom_id=f"sentrix:ticket-transcript:{int(ticket_id)}",
            row=0,
        )
    )
    return view


def _extract_log_ids(embed: discord.Embed) -> list[tuple[str, int]]:
    sample = "\n".join(
        [str(embed.description or "")]
        + [f"{field.name}\n{field.value}" for field in embed.fields]
    )
    result: list[tuple[str, int]] = []
    channel = re.search(r"<#(\d{15,22})>", sample)
    if channel:
        result.append(("Copier l'ID du salon", int(channel.group(1))))
    user = re.search(r"<@!?(\d{15,22})>", sample)
    if user:
        result.append(("Copier l'ID du membre", int(user.group(1))))
    return result


def _patch_tickets(bot: commands.Bot) -> None:
    global _PATCHED_TICKETS
    tickets_cog = bot.get_cog("Tickets")
    if tickets_cog is None:
        return
    if _PATCHED_TICKETS:
        return

    async def canonical_log_action(
        _self,
        guild: discord.Guild,
        embed: discord.Embed,
        log_channel_id: int | None = None,
    ):
        del log_channel_id
        ids = _extract_log_ids(embed)
        return await log_service.send_log(
            bot,
            guild,
            "tickets",
            embed,
            view=log_service.log_actions(ids=ids),
        )

    async def close_ticket_v6(
        _self,
        interaction: discord.Interaction,
        ticket_id: int,
        reason: str,
    ):
        ticket = await bot.db.fetchone("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        if not ticket or interaction.guild is None:
            return
        guild = interaction.guild
        channel = guild.get_channel(ticket["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return

        _remember_channel(channel)
        channel_id = int(channel.id)
        channel_name = _clean_channel_name(channel.name)
        opener_id = int(ticket["user_id"] or 0)
        closer_id = int(interaction.user.id)
        conf = await bot.db.get_guild_config(guild.id)

        await bot.db.execute(
            "UPDATE tickets SET status = 'ferme', closed_at = ?, locked = 1 WHERE id = ?",
            (int(time.time()), ticket_id),
        )

        owner = guild.get_member(opener_id)
        if owner:
            overwrite = channel.overwrites_for(owner)
            overwrite.send_messages = False
            try:
                await channel.set_permissions(owner, overwrite=overwrite)
            except discord.HTTPException:
                pass

        try:
            transcript_text = await _self._fetch_transcript_text(channel)
        except discord.HTTPException:
            transcript_text = "Transcription indisponible (erreur lors de la lecture du salon)."

        await _store_transcript(
            bot,
            ticket_id=ticket_id,
            guild_id=guild.id,
            channel_id=channel_id,
            channel_name=channel_name,
            text=transcript_text,
        )

        try:
            delay = int((conf["ticket_delete_delay"] if conf else 30) or 30)
        except (KeyError, TypeError, ValueError):
            delay = 30
        asyncio.create_task(_self._auto_delete(channel, ticket_id, delay))

        close_embed = embeds.warning(
            f"Ticket fermé par {interaction.user.mention}.\n"
            f"Raison : {reason}\n\n"
            f"Suppression automatique dans **{max(1, delay)} seconde(s)**."
        )
        try:
            await channel.send(
                embed=close_embed,
                view=_ticket_actions(
                    ticket_id=ticket_id,
                    channel_id=channel_id,
                    opener_id=opener_id,
                    closer_id=closer_id,
                ),
                allowed_mentions=log_service.LOG_ALLOWED_MENTIONS,
            )
        except discord.HTTPException:
            pass

        panel = embeds.log_embed(
            "Ticket fermé",
            fields=(
                ("Ticket", f"`#{ticket_id}`", True),
                ("Salon", _channel_value(channel), False),
                ("Ouvert par", f"<@{opener_id}>" if opener_id else "Utilisateur indisponible", True),
                ("Fermé par", interaction.user.mention, True),
                ("Raison", reason or "Aucune raison fournie", False),
                ("Transcript", "Disponible avec le bouton ci-dessous.", False),
            ),
        )
        event_key = log_service.make_event_key(
            guild.id,
            "ticket_close",
            target_id=opener_id or None,
            executor_id=closer_id,
            discriminator=ticket_id,
        )
        await log_service.send_log(
            bot,
            guild,
            "tickets",
            panel,
            view=_ticket_actions(
                ticket_id=ticket_id,
                channel_id=channel_id,
                opener_id=opener_id,
                closer_id=closer_id,
            ),
            event_key=event_key,
        )

        if owner:
            try:
                transcript_dm = True if not conf else bool(conf["ticket_transcript_dm"])
            except (KeyError, TypeError):
                transcript_dm = True
            if transcript_dm:
                try:
                    await owner.send(
                        embed=embeds.info(
                            f"Voici la transcription de votre ticket sur **{guild.name}**."
                        ),
                        file=_self._transcript_file(channel, transcript_text),
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass
            try:
                rating_enabled = True if not conf else bool(conf["ticket_rating_enabled"])
            except (KeyError, TypeError):
                rating_enabled = True
            if rating_enabled:
                try:
                    from .tickets import RatingView
                    await owner.send(
                        content="Pouvez-vous noter le support reçu ?",
                        view=RatingView(_self, ticket_id),
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

    canonical_log_action._sentrix_unified_v6 = True
    close_ticket_v6._sentrix_unified_v6 = True
    tickets_cog.log_action = types.MethodType(canonical_log_action, tickets_cog)
    tickets_cog.close_ticket = types.MethodType(close_ticket_v6, tickets_cog)
    _PATCHED_TICKETS = True


def _patch_raw_file_recovery(bot: commands.Bot) -> None:
    global _PATCHED_RAW_FILES
    logs_cog = bot.get_cog("Logs")
    if logs_cog is None or _PATCHED_RAW_FILES:
        return
    current = logs_cog._log_deleted_from_row

    async def with_file_archive(
        _self,
        guild: discord.Guild,
        row,
        *,
        fallback_channel_id: int | None = None,
    ):
        result = await current(
            guild,
            row,
            fallback_channel_id=fallback_channel_id,
        )
        try:
            raw = row["attachments"] or "[]"
            urls = json.loads(raw)
        except Exception:
            urls = []
        if urls:
            channel_id = int(row["channel_id"] or fallback_channel_id or 0)
            message_id = int(row["message_id"])
            author_id = int(row["author_id"])
            panel = embeds.log_embed(
                "Pièce jointe supprimée" if len(urls) == 1 else "Pièces jointes supprimées",
                fields=(
                    ("Salon", _channel_ref_v6(channel_id), False),
                    ("Auteur", f"<@{author_id}>", True),
                    ("Message", f"`{message_id}`", True),
                    ("Fichiers", "\n".join(str(url) for url in urls)[:1024], False),
                ),
            )
            await _send_files_log(
                bot,
                guild,
                panel,
                view=log_service.log_actions(
                    ids=[
                        ("Copier l'ID de l'auteur", author_id),
                        ("Copier l'ID du message", message_id),
                    ]
                ),
                event_key=log_service.make_event_key(
                    guild.id,
                    "deleted_files",
                    target_id=author_id,
                    message_id=message_id,
                ),
            )
        return result

    with_file_archive._sentrix_unified_v6 = True
    logs_cog._log_deleted_from_row = types.MethodType(with_file_archive, logs_cog)
    _PATCHED_RAW_FILES = True


class UnifiedLogsV6(commands.Cog, name="UnifiedLogsV6"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        _remember_channel(channel)

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self,
        before: discord.abc.GuildChannel,
        after: discord.abc.GuildChannel,
    ):
        _remember_channel(before)
        _remember_channel(after)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        # Le nom reste en mémoire pour tous les anciens embeds qui contiennent son ID.
        _remember_channel(channel)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.guild is None or message.author.bot or not message.attachments:
            return
        _remember_channel(message.channel)
        files = await _best_effort_files(list(message.attachments))
        lines = [_attachment_line(item) for item in message.attachments]
        panel = embeds.log_embed(
            "Image supprimée"
            if len(message.attachments) == 1
            and str(message.attachments[0].content_type or "").startswith("image/")
            else ("Fichier supprimé" if len(message.attachments) == 1 else "Fichiers supprimés"),
            fields=(
                ("Salon", _channel_value(message.channel), False),
                ("Auteur", message.author.mention, True),
                ("Message", f"`{message.id}`", True),
                ("Fichiers", "\n".join(lines)[:1024], False),
            ),
        )
        if files:
            image_file = next(
                (
                    file
                    for attachment, file in zip(message.attachments, files)
                    if str(getattr(attachment, "content_type", "") or "").startswith("image/")
                ),
                None,
            )
            if image_file is not None:
                panel.set_image(url=f"attachment://{image_file.filename}")
        await _send_files_log(
            self.bot,
            message.guild,
            panel,
            files=files,
            view=log_service.log_actions(
                ids=[
                    ("Copier l'ID de l'auteur", message.author.id),
                    ("Copier l'ID du message", message.id),
                ]
            ),
            event_key=log_service.make_event_key(
                message.guild.id,
                "deleted_files",
                target_id=message.author.id,
                message_id=message.id,
            ),
        )

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        data = interaction.data if isinstance(interaction.data, dict) else {}
        custom_id = str(data.get("custom_id") or "")
        prefix = "sentrix:ticket-transcript:"
        if not custom_id.startswith(prefix):
            return
        if interaction.response.is_done():
            return
        try:
            ticket_id = int(custom_id[len(prefix):])
        except ValueError:
            return
        row = await self.bot.db.fetchone(
            "SELECT * FROM ticket_transcripts WHERE ticket_id = ?",
            (ticket_id,),
        )
        if not row:
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error("Cette transcript n'est plus disponible.")), ephemere=True)
        if interaction.guild is None or int(row["guild_id"]) != interaction.guild.id:
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Cette transcript appartient à un autre serveur.')), ephemere=True)

        ticket = await self.bot.db.fetchone("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        allowed = bool(
            member
            and (
                member.id == interaction.guild.owner_id
                or member.guild_permissions.manage_channels
                or member.guild_permissions.administrator
                or (ticket and int(ticket["user_id"] or 0) == member.id)
            )
        )
        if not allowed:
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error("Vous n'avez pas accès à cette transcript.")), ephemere=True)

        name = _clean_channel_name(row["channel_name"])
        payload = io.BytesIO(str(row["transcript_text"] or "Aucun message.").encode("utf-8"))
        await interaction.response.send_message(
            file=discord.File(payload, filename=f"transcript-{name}.txt"),
            ephemeral=True,
        )


async def install(bot: commands.Bot) -> None:
    await _ensure_schema(bot)
    _install_routes()
    _install_visuals(bot)

    # Réaffirme V5.3 avant de brancher les producteurs V6 : pas de retour aux wrappers cassés.
    log_transport_v52.install(bot)
    _patch_reset_v2()
    _patch_tickets(bot)
    _patch_raw_file_recovery(bot)

    current = bot.get_cog("UnifiedLogsV6")
    if current is not None:
        await bot.remove_cog("UnifiedLogsV6")
    await bot.add_cog(UnifiedLogsV6(bot))

    logger.warning(
        "Logs V6 actifs : 9 routes, logs-dossiers, tickets/transcripts unifiés et barre large."
    )


async def setup(bot: commands.Bot) -> None:
    await install(bot)


__all__ = ["install", "LOG_BAR", "FILES_ROUTE", "UnifiedLogsV6"]
