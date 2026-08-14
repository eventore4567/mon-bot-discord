"""Résout globalement les réponses slash différées des commandes hybrides SentriX.

Principe : lorsqu'un Context issu d'une interaction appelle ``ctx.defer()``, on marque ce
contexte comme possédant une réponse originale à remplir. Le premier ``ctx.send()`` suivant
édite DIRECTEMENT cette réponse originale au lieu de faire un follow-up. Aucun fetch de la
réponse originale n'est nécessaire : le defer créé par SentriX est la preuve suffisante.

Cela couvre toutes les commandes hybrides utilisant le couple ctx.defer() -> ctx.send(),
sans modifier les commandes préfixées. Les envois suivants restent des follow-ups normaux.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import discord
from discord.ext import commands

logger = logging.getLogger("bot.deferred-context-response")

_DEFERRED_TYPES = {
    discord.InteractionResponseType.deferred_channel_message,
    discord.InteractionResponseType.deferred_message_update,
}
_EDIT_KEYS = {"embed", "embeds", "view", "allowed_mentions", "poll"}
_UNSUPPORTED_EDIT_KEYS = {
    "tts", "stickers", "nonce", "reference", "mention_author", "silent", "suppress_embeds"
}
_PENDING_ATTR = "_sentrix_deferred_original_pending"


def _state(bot: commands.Bot) -> dict:
    state = getattr(bot, "deferred_context_response_guard_state", None)
    if not isinstance(state, dict):
        state = {
            "installed": False,
            "installed_at": None,
            "defer_marked_count": 0,
            "resolved_count": 0,
            "fallback_count": 0,
            "last_resolved_at": None,
            "last_command_name": None,
            "last_result": None,
            "last_error": None,
        }
        bot.deferred_context_response_guard_state = state
    return state


def _safe_health(bot: commands.Bot) -> dict:
    state = _state(bot)
    return {
        "installed": bool(state.get("installed")),
        "installed_at": state.get("installed_at"),
        "defer_marked_count": int(state.get("defer_marked_count") or 0),
        "resolved_count": int(state.get("resolved_count") or 0),
        "fallback_count": int(state.get("fallback_count") or 0),
        "last_resolved_at": state.get("last_resolved_at"),
        "last_command_name": state.get("last_command_name"),
        "last_result": state.get("last_result"),
        "last_error": state.get("last_error"),
    }


def _install_health_patch() -> None:
    try:
        from web import production_health
    except Exception:
        return

    current = production_health._safe_slash_health
    if getattr(current, "_sentrix_deferred_context_response_health", False):
        return

    def safe_slash_health_with_context_guard(bot):
        payload = current(bot)
        if not isinstance(payload, dict):
            payload = {}
        payload["deferred_context_response_guard"] = _safe_health(bot)
        return payload

    safe_slash_health_with_context_guard._sentrix_deferred_context_response_health = True
    safe_slash_health_with_context_guard._sentrix_original = current
    production_health._safe_slash_health = safe_slash_health_with_context_guard


def _command_name(ctx: commands.Context) -> str | None:
    command = getattr(ctx, "command", None)
    name = getattr(command, "qualified_name", None) or getattr(command, "name", None)
    return str(name)[:120] if name else None


def _can_edit_from_send_kwargs(kwargs: dict[str, Any]) -> bool:
    for key in _UNSUPPORTED_EDIT_KEYS:
        value = kwargs.get(key)
        if value not in (None, False):
            return False
    return True


def _edit_kwargs(content: Any, kwargs: dict[str, Any]) -> tuple[dict[str, Any], float | None]:
    edit: dict[str, Any] = {"content": content}
    for key in _EDIT_KEYS:
        if key in kwargs and kwargs[key] is not None:
            edit[key] = kwargs[key]

    attachments: list[Any] = []
    file = kwargs.get("file")
    files = kwargs.get("files")
    if file is not None:
        attachments.append(file)
    if files is not None:
        attachments.extend(list(files))
    if attachments:
        edit["attachments"] = attachments

    delete_after = kwargs.get("delete_after")
    return edit, float(delete_after) if delete_after is not None else None


def _mark_pending(ctx: commands.Context) -> None:
    setattr(ctx, _PENDING_ATTR, True)
    runtime_bot = getattr(ctx, "bot", None)
    if isinstance(runtime_bot, commands.Bot):
        state = _state(runtime_bot)
        state["defer_marked_count"] = int(state.get("defer_marked_count") or 0) + 1
        state["last_command_name"] = _command_name(ctx)
        state["last_result"] = "defer_marked"
        state["last_error"] = None


def _consume_pending(ctx: commands.Context) -> bool:
    pending = bool(getattr(ctx, _PENDING_ATTR, False))
    if pending:
        setattr(ctx, _PENDING_ATTR, False)
    return pending


def install(bot: commands.Bot) -> None:
    current_send = commands.Context.send
    current_defer = commands.Context.defer

    if not getattr(current_defer, "_sentrix_marks_deferred_original", False):
        async def defer_marking_original(self: commands.Context, *args, **kwargs):
            interaction = getattr(self, "interaction", None)
            result = await current_defer(self, *args, **kwargs)
            if (
                interaction is not None
                and not interaction.is_expired()
                and interaction.response.is_done()
                and interaction.response.type in _DEFERRED_TYPES
            ):
                _mark_pending(self)
            return result

        defer_marking_original._sentrix_marks_deferred_original = True
        defer_marking_original._sentrix_original = current_defer
        commands.Context.defer = defer_marking_original

    if not getattr(current_send, "_sentrix_resolves_deferred_original", False):
        async def send_resolving_deferred_original(self: commands.Context, content=None, **kwargs):
            interaction = getattr(self, "interaction", None)
            pending = bool(getattr(self, _PENDING_ATTR, False))
            runtime_bot = getattr(self, "bot", None)
            state = _state(runtime_bot) if isinstance(runtime_bot, commands.Bot) else None

            if (
                not pending
                or interaction is None
                or interaction.is_expired()
                or not interaction.response.is_done()
                or interaction.response.type not in _DEFERRED_TYPES
                or not _can_edit_from_send_kwargs(kwargs)
            ):
                return await current_send(self, content, **kwargs)

            edit, delete_after = _edit_kwargs(content, kwargs)
            try:
                message = await interaction.edit_original_response(**edit)
                _consume_pending(self)
                if delete_after is not None:
                    await message.delete(delay=delete_after)
                if state is not None:
                    state["resolved_count"] = int(state.get("resolved_count") or 0) + 1
                    state["last_resolved_at"] = int(time.time())
                    state["last_command_name"] = _command_name(self)
                    state["last_result"] = "deferred_original_resolved_directly"
                    state["last_error"] = None
                return message
            except (discord.NotFound, discord.Forbidden, discord.HTTPException, discord.ClientException) as exc:
                _consume_pending(self)
                if state is not None:
                    state["fallback_count"] = int(state.get("fallback_count") or 0) + 1
                    state["last_result"] = "direct_edit_failed_followup_used"
                    state["last_error"] = type(exc).__name__
                return await current_send(self, content, **kwargs)

        send_resolving_deferred_original._sentrix_resolves_deferred_original = True
        send_resolving_deferred_original._sentrix_original = current_send
        commands.Context.send = send_resolving_deferred_original

    state = _state(bot)
    state["installed"] = True
    state["installed_at"] = int(time.time())
    state["last_error"] = None
    _install_health_patch()
    logger.info("Garde defer global active : premier ctx.send apres ctx.defer edite directement la reponse originale.")


async def setup(bot: commands.Bot) -> None:
    install(bot)
