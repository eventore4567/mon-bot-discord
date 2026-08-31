"""Keep /profile compact by rendering it as a native Discord embed.

Ordinary SentriX command embeds are intentionally converted to a Components V2 panel by
``command_visuals``. That works well for short command responses, but a profile contains
many statistics and becomes unnecessarily tall when every field is flattened into text.

/profile is a presentation exception: keep its real Discord embed so ``inline=True``
fields can use Discord's multi-column layout. The existing top-banner payload helper is
still used, so the SentriX banner stays above the profile instead of falling to the
bottom. Other commands are untouched.
"""
from __future__ import annotations

from typing import Any

import discord
from discord.ext import commands

from . import command_visuals as visuals

_INSTALLED = False
_PREVIOUS_CONTEXT_SEND = None


def _root_command_name(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    root = getattr(command, "root_parent", None) or command
    return str(getattr(root, "name", "") or "").casefold()


async def _compact_profile_send(self: commands.Context, *args: Any, **kwargs: Any):
    """Bypass Components V2 only for profile embeds."""
    assert _PREVIOUS_CONTEXT_SEND is not None

    if _root_command_name(self) != "profile":
        return await _PREVIOUS_CONTEXT_SEND(self, *args, **kwargs)

    # Respect explicit low-level/native sends and unusual payloads by letting the normal
    # renderer deal with them. The profile command itself sends one Discord Embed.
    if kwargs.get("_sentrix_native", False):
        return await _PREVIOUS_CONTEXT_SEND(self, *args, **kwargs)

    content = args[0] if args else kwargs.pop("content", None)
    embed = kwargs.get("embed")
    embeds = kwargs.get("embeds")

    has_native_embed = isinstance(embed, discord.Embed) or (
        isinstance(embeds, (list, tuple))
        and any(isinstance(item, discord.Embed) for item in embeds)
    )
    if not has_native_embed:
        return await _PREVIOUS_CONTEXT_SEND(self, *args, **kwargs)

    raw_send = getattr(visuals, "_ORIGINAL_CONTEXT_SEND", None)
    if raw_send is None:
        return await _PREVIOUS_CONTEXT_SEND(self, *args, **kwargs)

    # top_command_banners replaces visuals._native_payload during startup. Calling the
    # current helper therefore preserves the real embed AND keeps the banner first.
    native_content, native_kwargs = visuals._native_payload(self, content, embed, kwargs)
    return await raw_send(self, native_content, **native_kwargs)


def install_profile_embed_guard() -> None:
    """Install the compact /profile exception once, after command visuals are ready."""
    global _INSTALLED
    global _PREVIOUS_CONTEXT_SEND

    if _INSTALLED:
        return
    _INSTALLED = True

    current_send = commands.Context.send
    if getattr(current_send, "_sentrix_profile_embed_guard", False):
        _PREVIOUS_CONTEXT_SEND = getattr(
            current_send, "_sentrix_previous_context_send", current_send
        )
        return

    _PREVIOUS_CONTEXT_SEND = current_send
    _compact_profile_send._sentrix_profile_embed_guard = True
    _compact_profile_send._sentrix_previous_context_send = current_send
    commands.Context.send = _compact_profile_send


__all__ = ["install_profile_embed_guard"]
