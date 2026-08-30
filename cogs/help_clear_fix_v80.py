"""SentriX V80 — Help sans faux ping + logs complets de +clear.

Deux corrections ciblées :
- les textes du Help n'affichent plus @everyone/@here comme de vraies mentions Discord ;
- +clear et /clear produisent un journal de purge lisible avec aperçu des messages et
  transcription complète, au lieu de dépendre uniquement des événements de suppression.
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
import time

import discord
from discord.ext import commands

from utils import embeds, log_service
from . import help_complete_v79 as help_v79
from . import premium_ui_v81 as premium_v81
from . import premium_ui_v82 as premium_v82

logger = logging.getLogger("bot.help-clear-fix-v80")
RUNTIME_MARKER = "Help/Clear Fix V80"
_SUPPRESSION_TTL = 15.0


def _neutralize_mentions(value: object) -> str:
    """Garde le texte lisible sans transformer @everyone/@here en mention Discord."""
    text = str(value or "")
    return re.sub(r"@(everyone|here)\b", lambda m: "@\u200b" + m.group(1), text, flags=re.IGNORECASE)


def _install_help_safety() -> None:
    current_description = help_v79._description
    if not getattr(current_description, "_sentrix_v80_safe_mentions", False):
        def safe_description(entry):
            return _neutralize_mentions(current_description(entry))

        safe_description._sentrix_v80_safe_mentions = True
        safe_description._sentrix_previous = current_description
        help_v79._description = safe_description

    current_permission = help_v79._permission
    if not getattr(current_permission, "_sentrix_v80_safe_mentions", False):
        def safe_permission(entry):
            return _neutralize_mentions(current_permission(entry))

        safe_permission._sentrix_v80_safe_mentions = True
        safe_permission._sentrix_previous = current_permission
        help_v79._permission = safe_permission

    current_example = help_v79._example
    if not getattr(current_example, "_sentrix_v80_safe_mentions", False):
        def safe_example(entry, prefix):
            return _neutralize_mentions(current_example(entry, prefix))

        safe_example._sentrix_v80_safe_mentions = True
        safe_example._sentrix_previous = current_example
        help_v79._example = safe_example


def _suppression_map(bot: commands.Bot) -> dict[int, float]:
    mapping = getattr(bot, "_sentrix_clear_suppressed_v80", None)
    if mapping is None:
        mapping = {}
        bot._sentrix_clear_suppressed_v80 = mapping
    now_mono = time.monotonic()
    for message_id, expires_at in list(mapping.items()):
        if expires_at <= now_mono:
            mapping.pop(message_id, None)
    return mapping


def _mark_suppressed(bot: commands.Bot, message_ids: set[int]) -> None:
    expires_at = time.monotonic() + _SUPPRESSION_TTL
    mapping = _suppression_map(bot)
    for message_id in message_ids:
        mapping[int(message_id)] = expires_at


async def _release_suppressed(bot: commands.Bot, message_ids: set[int]) -> None:
    await asyncio.sleep(_SUPPRESSION_TTL)
    mapping = _suppression_map(bot)
    for message_id in message_ids:
        mapping.pop(int(message_id), None)


def _is_suppressed(bot: commands.Bot, message_id: int | None) -> bool:
    if not message_id:
        return False
    return int(message_id) in _suppression_map(bot)


def _logs_listener(function, method_name: str) -> bool:
    owner = getattr(function, "__self__", None)
    if owner is None:
        return False
    return owner.__class__.__name__ == "Logs" and getattr(function, "__name__", "") == method_name


def _install_clear_event_filter(bot: commands.Bot) -> None:
    """Empêche un +clear de créer N logs individuels avant le log récapitulatif V80."""
    extra_events = getattr(bot, "extra_events", None)
    if not isinstance(extra_events, dict):
        logger.warning("V80: extra_events indisponible, filtre de purge non installé.")
        return

    specs = (
        ("on_message_delete", "on_message_delete", "message"),
        ("on_raw_message_delete", "on_raw_message_delete", "raw"),
        ("on_raw_bulk_message_delete", "on_raw_bulk_message_delete", "bulk"),
    )
    for event_name, method_name, kind in specs:
        listeners = extra_events.get(event_name, [])
        for index, listener in enumerate(list(listeners)):
            if not _logs_listener(listener, method_name):
                continue
            if getattr(listener, "_sentrix_clear_filter_v80", False):
                continue

            original = listener

            if kind == "message":
                async def wrapper(message, _original=original):
                    if _is_suppressed(bot, getattr(message, "id", None)):
                        return
                    return await _original(message)
            elif kind == "raw":
                async def wrapper(payload, _original=original):
                    if _is_suppressed(bot, getattr(payload, "message_id", None)):
                        return
                    return await _original(payload)
            else:
                async def wrapper(payload, _original=original):
                    message_ids = {int(value) for value in getattr(payload, "message_ids", set())}
                    if message_ids and all(_is_suppressed(bot, value) for value in message_ids):
                        return
                    return await _original(payload)

            wrapper._sentrix_clear_filter_v80 = True
            wrapper._sentrix_previous = original
            listeners[index] = wrapper


def _message_preview(messages: list[discord.Message], limit: int = 10) -> str:
    rows: list[str] = []
    budget = 1000
    for message in messages[:limit]:
        author = _neutralize_mentions(getattr(message.author, "display_name", str(message.author)))
        content = _neutralize_mentions(message.content or "[message sans texte]")
        content = discord.utils.escape_markdown(content).replace("\n", " ").strip()
        if len(content) > 150:
            content = content[:149].rstrip() + "…"
        row = f"**{author}** — {content}"
        if len("\n".join([*rows, row])) > budget:
            break
        rows.append(row)
    return "\n".join(rows) if rows else "Aucun contenu texte disponible."


def _transcript_bytes(ctx: commands.Context, messages: list[discord.Message], requested: int) -> bytes:
    lines = [
        "SentriX — transcription de clear",
        f"Serveur: {ctx.guild.name} ({ctx.guild.id})",
        f"Salon: #{ctx.channel.name} ({ctx.channel.id})",
        f"Modérateur: {ctx.author} ({ctx.author.id})",
        f"Demandé: {requested}",
        f"Supprimé: {len(messages)}",
        "",
    ]
    for index, message in enumerate(sorted(messages, key=lambda m: m.created_at), start=1):
        content = message.content or "[message sans texte]"
        lines.append(
            f"[{index}] {message.created_at.isoformat()} | {message.author} ({message.author.id}) | "
            f"message={message.id}"
        )
        lines.append(content)
        if message.attachments:
            lines.append("Pièces jointes: " + " | ".join(attachment.url for attachment in message.attachments))
        lines.append("")
    return "\n".join(lines).encode("utf-8", errors="replace")


async def _send_clear_log(
    bot: commands.Bot,
    ctx: commands.Context,
    messages: list[discord.Message],
    *,
    requested: int,
) -> None:
    if ctx.guild is None:
        return

    preview = _message_preview(messages)
    panel = embeds.log_embed(
        "Messages supprimés avec Clear",
        fields=(
            ("Modérateur", f"<@{ctx.author.id}>", True),
            ("Salon", f"<#{ctx.channel.id}>", True),
            ("Nombre", str(len(messages)), True),
            ("Messages supprimés", preview, False),
            (
                "Transcription",
                "Le fichier joint contient la totalité des messages supprimés, leurs auteurs, IDs et pièces jointes.",
                False,
            ),
        ),
    )

    transcript = _transcript_bytes(ctx, messages, requested)
    file: discord.File | None = None
    try:
        setting = await log_service.get_log_setting(bot, ctx.guild.id, "messages")
        if setting.get("enabled"):
            ok, _reason = log_service.validate_channel(
                ctx.guild,
                setting.get("channel_id"),
                needs_file=True,
            )
            if ok:
                file = discord.File(
                    io.BytesIO(transcript),
                    filename=f"sentrix-clear-{ctx.channel.id}-{int(time.time())}.txt",
                )
    except Exception:
        logger.debug("V80: vérification de la permission fichier impossible", exc_info=True)

    event_key = log_service.make_event_key(
        ctx.guild.id,
        "clear_command",
        executor_id=ctx.author.id,
        discriminator=time.time_ns(),
    )
    await log_service.send_log(
        bot,
        ctx.guild,
        "messages",
        panel,
        file=file,
        event_key=event_key,
    )


async def _clear_v80(self, ctx: commands.Context, nombre: int):
    requested = max(1, min(int(nombre), 100))
    if ctx.interaction and not ctx.interaction.response.is_done():
        await ctx.interaction.response.defer(ephemeral=True)

    is_prefix = ctx.interaction is None
    purge_limit = requested + (1 if is_prefix else 0)
    invocation_id = getattr(getattr(ctx, "message", None), "id", None) if is_prefix else None

    # Marquer AVANT la suppression afin que les listeners de logs ignorent les événements
    # individuels générés par Discord et laissent V80 produire un seul journal propre.
    candidates = [message async for message in ctx.channel.history(limit=purge_limit)]
    candidate_ids = {int(message.id) for message in candidates}
    _mark_suppressed(self.bot, candidate_ids)
    asyncio.create_task(_release_suppressed(self.bot, candidate_ids))

    deleted = await ctx.channel.purge(limit=purge_limit)
    messages = [
        message for message in deleted
        if invocation_id is None or int(message.id) != int(invocation_id)
    ]

    await _send_clear_log(self.bot, ctx, messages, requested=requested)

    response = embeds.success(f"{len(messages)} message(s) supprimé(s).")
    if ctx.interaction:
        await ctx.send(embed=response, ephemeral=True)
    else:
        await ctx.send(embed=response, delete_after=5)


def _install_clear_command(bot: commands.Bot) -> None:
    command = bot.get_command("clear")
    if command is None:
        logger.warning("V80: commande clear introuvable.")
        return
    current = command.callback
    if getattr(current, "_sentrix_clear_v80", False):
        return
    _clear_v80._sentrix_clear_v80 = True
    _clear_v80._sentrix_previous = current
    command.callback = _clear_v80


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_help_clear_fix_v80", False):
        return
    _install_help_safety()
    _install_clear_event_filter(bot)
    _install_clear_command(bot)
    premium_v81.install(bot)
    premium_v82.install(bot)
    bot._sentrix_help_clear_fix_v80 = True
    logger.info(
        "%s installé : mentions du Help neutralisées, clear complet et Premium UI V82 chargée.",
        RUNTIME_MARKER,
    )


__all__ = ["install", "_neutralize_mentions"]
