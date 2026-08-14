"""Corrige globalement le pattern ``ctx.defer()`` puis ``ctx.send()`` des commandes hybrides.

Dans discord.py, Context.send() utilise un follow-up des que InteractionResponse est deja
terminee. Apres Context.defer(), cela laisse donc potentiellement la reponse originale vide
sur « thinking » pendant que le vrai resultat part dans un second message.

SentriX intercepte uniquement ce cas precis :
- contexte issu d'une interaction encore valide ;
- reponse Discord de type deferred_channel_message/deferred_message_update ;
- reponse originale encore vide.

Le premier Context.send() remplit alors la reponse originale. Si elle contient deja un vrai
payload, le Context.send() original est appele et produit normalement un follow-up. Les
commandes prefixees ne changent jamais de comportement.
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
_UNSUPPORTED_EDIT_KEYS = {"tts", "stickers", "nonce", "reference", "mention_author", "silent", "suppress_embeds"}


def _state(bot: commands.Bot) -> dict:
    state = getattr(bot, "deferred_context_response_guard_state", None)
    if not isinstance(state, dict):
        state = {
            "installed": False,
            "installed_at": None,
            "resolved_count": 0,
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
        "resolved_count": int(state.get("resolved_count") or 0),
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


def _has_payload(message: discord.InteractionMessage) -> bool:
    return bool(
        (getattr(message, "content", "") or "").strip()
        or getattr(message, "embeds", None)
        or getattr(message, "attachments", None)
        or getattr(message, "components", None)
        or getattr(message, "stickers", None)
        or getattr(message, "poll", None)
    )


def _can_edit_from_send_kwargs(kwargs: dict[str, Any]) -> bool:
    # Les valeurs par defaut False/None ne bloquent pas l'edition. Une option réellement
    # demandee mais non representable par edit_original_response reste un follow-up normal.
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


def install(bot: commands.Bot) -> None:
    current = commands.Context.send
    if getattr(current, "_sentrix_resolves_deferred_original", False):
        state = _state(bot)
        state["installed"] = True
        _install_health_patch()
        return

    async def send_resolving_deferred_original(self: commands.Context, content=None, **kwargs):
        interaction = getattr(self, "interaction", None)
        if (
            interaction is None
            or interaction.is_expired()
            or not interaction.response.is_done()
            or interaction.response.type not in _DEFERRED_TYPES
            or not _can_edit_from_send_kwargs(kwargs)
        ):
            return await current(self, content, **kwargs)

        runtime_bot = getattr(self, "bot", None)
        state = _state(runtime_bot) if isinstance(runtime_bot, commands.Bot) else None
        try:
            original = await interaction.original_response()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, discord.ClientException) as exc:
            if state is not None:
                state["last_result"] = "original_unavailable"
                state["last_error"] = type(exc).__name__
            return await current(self, content, **kwargs)

        if _has_payload(original):
            if state is not None:
                state["last_result"] = "original_already_resolved"
                state["last_error"] = None
            return await current(self, content, **kwargs)

        edit, delete_after = _edit_kwargs(content, kwargs)
        try:
            message = await interaction.edit_original_response(**edit)
            if delete_after is not None:
                await message.delete(delay=delete_after)
            if state is not None:
                state["resolved_count"] = int(state.get("resolved_count") or 0) + 1
                state["last_resolved_at"] = int(time.time())
                state["last_command_name"] = _command_name(self)
                state["last_result"] = "deferred_original_resolved"
                state["last_error"] = None
            return message
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
            if state is not None:
                state["last_result"] = "edit_failed_followup_used"
                state["last_error"] = type(exc).__name__
            # Ne jamais perdre la vraie reponse : si l'edition originale echoue, le
            # Context.send natif garde son comportement de follow-up.
            return await current(self, content, **kwargs)

    send_resolving_deferred_original._sentrix_resolves_deferred_original = True
    send_resolving_deferred_original._sentrix_original = current
    commands.Context.send = send_resolving_deferred_original

    state = _state(bot)
    state["installed"] = True
    state["installed_at"] = int(time.time())
    state["last_error"] = None
    _install_health_patch()
    logger.info("Context.send protege : un premier envoi apres defer resout maintenant la reponse originale.")


async def setup(bot: commands.Bot) -> None:
    install(bot)
