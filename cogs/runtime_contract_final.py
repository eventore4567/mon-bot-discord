"""Contrat runtime final SentriX.

Garantit trois règles : logs compatibles ``view=``, réponses de commandes en embeds,
et conversation directe avec ``sentrix`` en texte normal.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import discord
from discord.ext import commands

from utils import embeds as sentrix_embeds
from utils import log_service

logger = logging.getLogger("bot.runtime-contract-final")
_PLAIN_AI_TOKENS: dict[str, float] = {}


def _unwrap(callable_obj):
    seen: set[int] = set()
    current = callable_obj
    while hasattr(current, "_sentrix_original") and id(current) not in seen:
        seen.add(id(current))
        current = getattr(current, "_sentrix_original")
    return current


def _root_name(command: Any) -> str:
    if command is None:
        return ""
    root = getattr(command, "root_parent", None) or command
    return str(
        getattr(root, "name", "")
        or getattr(command, "qualified_name", "")
        or getattr(command, "name", "")
        or ""
    ).split()[0].casefold()


def _plain_ai_context(ctx: commands.Context) -> bool:
    return _root_name(getattr(ctx, "command", None)) == "sentrix"


def _plain_ai_interaction(interaction: discord.Interaction | None) -> bool:
    return bool(interaction) and _root_name(getattr(interaction, "command", None)) == "sentrix"


def _remember_ai_interaction(interaction: discord.Interaction | None) -> None:
    if not _plain_ai_interaction(interaction):
        return
    token = str(getattr(interaction, "token", "") or "")
    if not token:
        return
    now = time.monotonic()
    _PLAIN_AI_TOKENS[token] = now
    if len(_PLAIN_AI_TOKENS) > 256:
        cutoff = now - 1200
        for key, stamp in list(_PLAIN_AI_TOKENS.items()):
            if stamp < cutoff:
                _PLAIN_AI_TOKENS.pop(key, None)


def _normalize(args: tuple, kwargs: dict, *, editing: bool = False):
    """Réutilise le renderer officiel pour toutes les commandes normales."""
    try:
        from . import final_interaction_policy
        return final_interaction_policy._normalize_payload(
            args, kwargs, editing=editing, force_embed=True
        )
    except Exception:
        new_args = list(args)
        new_kwargs = dict(kwargs)
        content = new_kwargs.get("content")
        positional = False
        if content is None and new_args:
            content = new_args[0]
            positional = True
        has_embed = new_kwargs.get("embed") is not None or bool(new_kwargs.get("embeds"))
        has_file = any(new_kwargs.get(key) is not None for key in ("file", "files"))
        if content is not None and str(content).strip() and not has_embed and not has_file:
            new_kwargs["embed"] = sentrix_embeds.standard("Information", str(content)[:4096])
            if positional:
                new_args[0] = None
            else:
                new_kwargs["content"] = None
        if editing and (new_kwargs.get("embed") is not None or new_kwargs.get("embeds")):
            new_kwargs["content"] = None
        return tuple(new_args), new_kwargs


async def _stable_send_log(
    bot,
    guild: discord.Guild,
    log_type: str,
    embed: discord.Embed,
    file: discord.File | None = None,
    *,
    files: list[discord.File] | None = None,
    view: discord.ui.View | None = None,
    event_key: str | None = None,
    **_ignored,
) -> bool:
    """Sender canonique qui accepte toujours ``view`` et les pièces jointes."""
    if guild is None or not isinstance(embed, discord.Embed):
        return False
    if not log_service.is_primary_process():
        logger.info("Log ignoré par SENTRIX_LOG_PRODUCER guild=%s type=%s", guild.id, log_type)
        return False

    rendered = (
        embed
        if getattr(getattr(embed, "image", None), "url", None) == sentrix_embeds.SENTRIX_BANNER_URL
        else sentrix_embeds.normalize_log(embed)
    )
    semantic_key = log_service.semantic_event_key(guild.id, log_type, rendered)
    if log_service._is_duplicate(event_key) or log_service._is_duplicate(semantic_key):
        logger.debug("Log dupliqué ignoré guild=%s type=%s", guild.id, log_type)
        return False

    try:
        setting = await log_service.get_log_setting(bot, guild.id, log_type)
    except Exception:
        logger.exception("Configuration log illisible guild=%s type=%s", guild.id, log_type)
        return False
    if not setting.get("enabled"):
        logger.info("Log désactivé guild=%s type=%s", guild.id, log_type)
        return False

    attached = [item for item in (files or []) if item is not None]
    if file is not None:
        attached.insert(0, file)
    ok, reason = log_service.validate_channel(
        guild, setting.get("channel_id"), needs_file=bool(attached)
    )
    if not ok:
        logger.warning("Log %s non envoyé sur guild=%s : %s", log_type, guild.id, reason)
        return False

    channel = guild.get_channel(int(setting["channel_id"]))
    if channel is None:
        return False
    send_kwargs: dict[str, Any] = {
        "embed": rendered,
        "allowed_mentions": log_service.LOG_ALLOWED_MENTIONS,
    }
    if view is not None:
        send_kwargs["view"] = view
    if len(attached) == 1:
        send_kwargs["file"] = attached[0]
    elif len(attached) > 1:
        send_kwargs["files"] = attached[:10]
    try:
        await channel.send(**send_kwargs)
        logger.info("Log envoyé guild=%s type=%s channel=%s", guild.id, log_type, channel.id)
        return True
    except (discord.Forbidden, discord.HTTPException):
        logger.exception("Échec d'envoi du log %s dans %s", log_type, setting.get("channel_id"))
        return False


def _install_log_contract() -> None:
    current = log_service.send_log
    if getattr(current, "_sentrix_stable_log_contract", False):
        return
    _stable_send_log._sentrix_stable_log_contract = True
    _stable_send_log._sentrix_replaced = current
    log_service.send_log = _stable_send_log


def _install_context_contract() -> None:
    current = commands.Context.send
    if getattr(current, "_sentrix_runtime_contract", False):
        return
    base = _unwrap(current)

    async def context_send(self: commands.Context, *args, **kwargs):
        if _plain_ai_context(self):
            return await base(self, *args, **kwargs)
        args, kwargs = _normalize(args, kwargs)
        return await base(self, *args, **kwargs)

    context_send._sentrix_runtime_contract = True
    context_send._sentrix_original = base
    commands.Context.send = context_send


def _install_interaction_contract() -> None:
    current_send = discord.InteractionResponse.send_message
    if not getattr(current_send, "_sentrix_runtime_contract", False):
        base_send = _unwrap(current_send)

        async def response_send(self, *args, **kwargs):
            interaction = getattr(self, "_parent", None)
            if _plain_ai_interaction(interaction):
                _remember_ai_interaction(interaction)
                return await base_send(self, *args, **kwargs)
            args, kwargs = _normalize(args, kwargs)
            return await base_send(self, *args, **kwargs)

        response_send._sentrix_runtime_contract = True
        response_send._sentrix_original = base_send
        discord.InteractionResponse.send_message = response_send

    current_edit = discord.InteractionResponse.edit_message
    if not getattr(current_edit, "_sentrix_runtime_contract", False):
        base_edit = _unwrap(current_edit)

        async def response_edit(self, *args, **kwargs):
            interaction = getattr(self, "_parent", None)
            if _plain_ai_interaction(interaction):
                _remember_ai_interaction(interaction)
                return await base_edit(self, *args, **kwargs)
            args, kwargs = _normalize(args, kwargs, editing=True)
            return await base_edit(self, *args, **kwargs)

        response_edit._sentrix_runtime_contract = True
        response_edit._sentrix_original = base_edit
        discord.InteractionResponse.edit_message = response_edit

    current_original_edit = discord.Interaction.edit_original_response
    if not getattr(current_original_edit, "_sentrix_runtime_contract", False):
        base_original_edit = _unwrap(current_original_edit)

        async def original_edit(self: discord.Interaction, *args, **kwargs):
            if _plain_ai_interaction(self):
                _remember_ai_interaction(self)
                return await base_original_edit(self, *args, **kwargs)
            args, kwargs = _normalize(args, kwargs, editing=True)
            return await base_original_edit(self, *args, **kwargs)

        original_edit._sentrix_runtime_contract = True
        original_edit._sentrix_original = base_original_edit
        discord.Interaction.edit_original_response = original_edit


def _install_followup_contract() -> None:
    current = discord.Webhook.send
    if getattr(current, "_sentrix_runtime_contract", False):
        return
    base = _unwrap(current)

    async def webhook_send(self: discord.Webhook, *args, **kwargs):
        token = str(getattr(self, "token", "") or "")
        if token and token in _PLAIN_AI_TOKENS:
            return await base(self, *args, **kwargs)
        if getattr(self, "type", None) == discord.WebhookType.application:
            args, kwargs = _normalize(args, kwargs)
            return await base(self, *args, **kwargs)
        return await base(self, *args, **kwargs)

    webhook_send._sentrix_runtime_contract = True
    webhook_send._sentrix_original = base
    discord.Webhook.send = webhook_send


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_runtime_contract_final", False):
        return
    _install_log_contract()
    _install_context_contract()
    _install_interaction_contract()
    _install_followup_contract()
    bot._sentrix_runtime_contract_final = True
    logger.info(
        "Contrat final actif : logs compatibles view=, commandes en embeds, conversation SentriX en texte."
    )


__all__ = ["install"]
