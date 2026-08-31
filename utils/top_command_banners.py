"""Keep SentriX command banners above classic interactive panels.

``utils.command_visuals`` uses Components V2 for ordinary command responses, where the
banner is naturally the first component. Some commands must stay on classic embeds
because their existing ``discord.ui.View`` callbacks edit embeds directly (stats, help,
setup, configuration panels, etc.). Discord always renders ``Embed.set_image`` *after*
the embed body, which is why those banners appeared at the bottom.

This compatibility layer keeps those classic views intact but renders the SentriX banner
as a tiny first embed followed by the real body embed. It also preserves that two-embed
order on later button/select edits. The patch is deliberately scoped to messages whose
first embed is one of the SentriX command banners; logs and unrelated Discord messages
are never intercepted.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

import discord
from discord.ext import commands

from . import command_visuals as visuals
from . import embeds as embed_factory

logger = logging.getLogger("bot.command-visuals.top-banner")

_INSTALLED = False
_ORIGINAL_INTERACTION_RESPONSE_EDIT = None
_ORIGINAL_INTERACTION_EDIT_ORIGINAL = None
_ORIGINAL_MESSAGE_EDIT = None


def _image_url(embed: discord.Embed | None) -> str:
    if not isinstance(embed, discord.Embed):
        return ""
    return str(getattr(getattr(embed, "image", None), "url", None) or "")


def _is_banner_header(embed: discord.Embed | None) -> bool:
    """Return True only for the dedicated image-only SentriX header embed."""
    if not isinstance(embed, discord.Embed) or not visuals._is_command_banner(_image_url(embed)):
        return False
    return not any((
        embed.title,
        embed.description,
        embed.fields,
        getattr(getattr(embed, "author", None), "name", None),
        getattr(getattr(embed, "footer", None), "text", None),
    ))


def _without_bottom_command_banner(embed: discord.Embed) -> discord.Embed:
    """Copy an embed while removing only the automatic SentriX command image.

    Semantic images (profile cards, generated images, level-up cards, etc.) are kept.
    ``to_dict``/``from_dict`` is used instead of relying on a particular discord.py
    ``remove_image`` implementation.
    """
    data = embed.to_dict()
    image = data.get("image") or {}
    if visuals._is_command_banner(image.get("url")):
        data.pop("image", None)
    return discord.Embed.from_dict(data)


def _banner_header(kind: str, body: discord.Embed | None = None) -> discord.Embed:
    colour_value = 0
    if body is not None and getattr(body, "colour", None) is not None:
        colour_value = int(getattr(body.colour, "value", 0) or 0)
    if not colour_value:
        colour_value = int(visuals._ACCENTS.get(kind, visuals._ACCENTS["info"]))
    header = discord.Embed(colour=discord.Colour(colour_value))
    header.set_image(url=visuals.banner_url(kind))
    return header


def _stack_for_embed(embed: discord.Embed, kind: str) -> list[discord.Embed]:
    body = _without_bottom_command_banner(embed)
    return [_banner_header(kind, body), body]


def _stack_for_embeds(values: Iterable[discord.Embed], kind: str | None = None) -> list[discord.Embed]:
    source = [item for item in values if isinstance(item, discord.Embed)]
    if not source:
        return []

    # Drop a previous header before rebuilding, making repeated edits idempotent.
    bodies = source[1:] if _is_banner_header(source[0]) else source
    cleaned = [_without_bottom_command_banner(item) for item in bodies]
    if not cleaned:
        return source

    resolved = kind or visuals.resolve_kind(None, embed=cleaned[0])
    # Discord allows at most ten embeds per message. Do not break an existing edge case
    # that already uses all ten slots just to add decoration.
    if len(cleaned) >= 10:
        return cleaned[:10]
    return [_banner_header(resolved, cleaned[0]), *cleaned[:9]]


def _native_payload_top(
    ctx: commands.Context,
    content: object,
    embed: discord.Embed | None,
    kwargs: dict[str, Any],
) -> tuple[object, dict[str, Any]]:
    """Replacement for command_visuals._native_payload with a real top banner."""
    output = dict(kwargs)

    existing_embeds = output.get("embeds")
    if existing_embeds:
        source = [item for item in existing_embeds if isinstance(item, discord.Embed)]
        if source:
            kind = visuals.resolve_kind(ctx, embed=source[0], content=content)
            output["embeds"] = _stack_for_embeds(source, kind)
        return content, output

    kind = visuals.resolve_kind(ctx, embed=embed, content=content)
    if isinstance(embed, discord.Embed):
        output.pop("embed", None)
        output["embeds"] = _stack_for_embed(embed, kind)
        return content, output

    if content is not None:
        panel = discord.Embed(
            title=visuals._human_command_name(ctx),
            description=visuals._clean_text(content, limit=3900) or None,
            colour=discord.Colour(visuals._ACCENTS[kind]),
        )
        output.pop("embed", None)
        output["embeds"] = _stack_for_embed(panel, kind)
        return None, output

    return content, output


def _message_has_top_banner(message: Any) -> bool:
    current = list(getattr(message, "embeds", None) or [])
    return bool(current and _is_banner_header(current[0]))


def _rewrite_edit_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Preserve the header whenever a classic callback replaces its body embed."""
    output = dict(kwargs)

    if "embed" in output:
        value = output.get("embed")
        if isinstance(value, discord.Embed):
            kind = visuals.resolve_kind(None, embed=value)
            output.pop("embed", None)
            output["embeds"] = _stack_for_embed(value, kind)
        # embed=None intentionally means "remove the embed"; respect it.
        return output

    if "embeds" in output:
        values = output.get("embeds")
        if values:
            source = [item for item in values if isinstance(item, discord.Embed)]
            if source:
                output["embeds"] = _stack_for_embeds(source)
    return output


async def _interaction_response_edit(self, *args: Any, **kwargs: Any):
    assert _ORIGINAL_INTERACTION_RESPONSE_EDIT is not None
    interaction = getattr(self, "_parent", None)
    message = getattr(interaction, "message", None)
    if _message_has_top_banner(message):
        kwargs = _rewrite_edit_kwargs(kwargs)
    return await _ORIGINAL_INTERACTION_RESPONSE_EDIT(self, *args, **kwargs)


async def _interaction_edit_original(self, *args: Any, **kwargs: Any):
    assert _ORIGINAL_INTERACTION_EDIT_ORIGINAL is not None
    message = getattr(self, "message", None)
    if _message_has_top_banner(message):
        kwargs = _rewrite_edit_kwargs(kwargs)
    return await _ORIGINAL_INTERACTION_EDIT_ORIGINAL(self, *args, **kwargs)


async def _message_edit(self, *args: Any, **kwargs: Any):
    assert _ORIGINAL_MESSAGE_EDIT is not None
    if _message_has_top_banner(self):
        kwargs = _rewrite_edit_kwargs(kwargs)
    return await _ORIGINAL_MESSAGE_EDIT(self, *args, **kwargs)


def install_top_command_banners() -> None:
    """Install the top-banner compatibility layer once."""
    global _INSTALLED
    global _ORIGINAL_INTERACTION_RESPONSE_EDIT
    global _ORIGINAL_INTERACTION_EDIT_ORIGINAL
    global _ORIGINAL_MESSAGE_EDIT

    if _INSTALLED:
        return
    _INSTALLED = True

    # The old factory inserted ``set_image`` directly into every embed created by
    # utils.embeds, including callbacks that bypass Context.send. Restore the original
    # factory and let the command renderer own banner placement instead.
    original_base = getattr(visuals, "_ORIGINAL_EMBED_BASE", None)
    if original_base is not None:
        embed_factory._base = original_base

    # ``_styled_context_send`` resolves this module global at call time, so replacing the
    # helper is sufficient for every classic command path and every native fallback.
    visuals._native_payload = _native_payload_top

    original_response_edit = discord.InteractionResponse.edit_message
    if not getattr(original_response_edit, "_sentrix_top_banner", False):
        _ORIGINAL_INTERACTION_RESPONSE_EDIT = original_response_edit
        _interaction_response_edit._sentrix_top_banner = True
        _interaction_response_edit._sentrix_original_edit = original_response_edit
        discord.InteractionResponse.edit_message = _interaction_response_edit
    else:
        _ORIGINAL_INTERACTION_RESPONSE_EDIT = getattr(
            original_response_edit, "_sentrix_original_edit", original_response_edit
        )

    original_edit_original = discord.Interaction.edit_original_response
    if not getattr(original_edit_original, "_sentrix_top_banner", False):
        _ORIGINAL_INTERACTION_EDIT_ORIGINAL = original_edit_original
        _interaction_edit_original._sentrix_top_banner = True
        _interaction_edit_original._sentrix_original_edit = original_edit_original
        discord.Interaction.edit_original_response = _interaction_edit_original
    else:
        _ORIGINAL_INTERACTION_EDIT_ORIGINAL = getattr(
            original_edit_original, "_sentrix_original_edit", original_edit_original
        )

    original_message_edit = discord.Message.edit
    if not getattr(original_message_edit, "_sentrix_top_banner", False):
        _ORIGINAL_MESSAGE_EDIT = original_message_edit
        _message_edit._sentrix_top_banner = True
        _message_edit._sentrix_original_edit = original_message_edit
        discord.Message.edit = _message_edit
    else:
        _ORIGINAL_MESSAGE_EDIT = getattr(original_message_edit, "_sentrix_original_edit", original_message_edit)

    logger.info("Command top banners installed: classic interactive panels keep banner first")


__all__ = ["install_top_command_banners"]
