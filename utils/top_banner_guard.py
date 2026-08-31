"""Final safety net for SentriX command banners.

The main command renderer already puts banners first for ``Context.send``. This guard
covers the remaining Discord interaction transports used by slash-command callbacks and
followups, and recognises the dedicated ping header as a command banner too.

Only payloads that already contain a known SentriX command banner are rewritten. Logs,
semantic images, generated images, profile cards and ordinary channel messages are left
untouched.
"""
from __future__ import annotations

import re
from typing import Any

import discord

from . import command_visuals as visuals
from . import top_command_banners as top_banners

_INSTALLED = False
_ORIGINAL_BANNER_CHECK = None
_ORIGINAL_INTERACTION_SEND = None
_ORIGINAL_WEBHOOK_SEND = None

_EXTRA_BANNER_RE = re.compile(r"/sentrix-ping-header\.webp(?:\?.*)?$", re.IGNORECASE)


def _extended_banner_check(url: object) -> bool:
    text = str(url or "")
    original = _ORIGINAL_BANNER_CHECK
    if original is not None:
        try:
            if original(url):
                return True
        except Exception:
            pass
    return bool(_EXTRA_BANNER_RE.search(text))


def _has_known_banner(embed: discord.Embed | None) -> bool:
    if not isinstance(embed, discord.Embed):
        return False
    image_url = getattr(getattr(embed, "image", None), "url", None)
    return _extended_banner_check(image_url)


def _rewrite_send_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Move an existing SentriX banner from embed.image to the first embed slot."""
    output = dict(kwargs)

    value = output.get("embed")
    if isinstance(value, discord.Embed) and _has_known_banner(value):
        kind = visuals.resolve_kind(None, embed=value)
        output.pop("embed", None)
        output["embeds"] = top_banners._stack_for_embed(value, kind)
        return output

    values = output.get("embeds")
    if isinstance(values, (list, tuple)):
        source = [item for item in values if isinstance(item, discord.Embed)]
        if source and any(_has_known_banner(item) or top_banners._is_banner_header(item) for item in source):
            output["embeds"] = top_banners._stack_for_embeds(source)

    return output


async def _interaction_send_message(self, *args: Any, **kwargs: Any):
    assert _ORIGINAL_INTERACTION_SEND is not None
    return await _ORIGINAL_INTERACTION_SEND(self, *args, **_rewrite_send_kwargs(kwargs))


async def _webhook_send(self, *args: Any, **kwargs: Any):
    assert _ORIGINAL_WEBHOOK_SEND is not None
    return await _ORIGINAL_WEBHOOK_SEND(self, *args, **_rewrite_send_kwargs(kwargs))


def install_top_banner_guard() -> None:
    """Install the final command-banner transport guard once."""
    global _INSTALLED
    global _ORIGINAL_BANNER_CHECK
    global _ORIGINAL_INTERACTION_SEND
    global _ORIGINAL_WEBHOOK_SEND

    if _INSTALLED:
        return
    _INSTALLED = True

    current_check = visuals._is_command_banner
    if not getattr(current_check, "_sentrix_extended_banner_check", False):
        _ORIGINAL_BANNER_CHECK = current_check
        _extended_banner_check._sentrix_extended_banner_check = True
        _extended_banner_check._sentrix_original_banner_check = current_check
        visuals._is_command_banner = _extended_banner_check
    else:
        _ORIGINAL_BANNER_CHECK = getattr(
            current_check, "_sentrix_original_banner_check", current_check
        )

    current_interaction_send = discord.InteractionResponse.send_message
    if not getattr(current_interaction_send, "_sentrix_top_banner_guard", False):
        _ORIGINAL_INTERACTION_SEND = current_interaction_send
        _interaction_send_message._sentrix_top_banner_guard = True
        _interaction_send_message._sentrix_original_send = current_interaction_send
        discord.InteractionResponse.send_message = _interaction_send_message
    else:
        _ORIGINAL_INTERACTION_SEND = getattr(
            current_interaction_send, "_sentrix_original_send", current_interaction_send
        )

    current_webhook_send = discord.Webhook.send
    if not getattr(current_webhook_send, "_sentrix_top_banner_guard", False):
        _ORIGINAL_WEBHOOK_SEND = current_webhook_send
        _webhook_send._sentrix_top_banner_guard = True
        _webhook_send._sentrix_original_send = current_webhook_send
        discord.Webhook.send = _webhook_send
    else:
        _ORIGINAL_WEBHOOK_SEND = getattr(
            current_webhook_send, "_sentrix_original_send", current_webhook_send
        )


__all__ = ["install_top_banner_guard"]
