"""Final single-panel renderer for SentriX command responses.

The historical command presentation stack contains compatibility layers for classic
Discord embeds and persistent views. Those layers are useful, but when several of them
see the same command response they can turn one logical answer into two visual cards: an
image-only banner embed followed by the real embed.

This module is installed last. For simple command responses it bypasses the compatibility
stack and renders one Components V2 container containing the banner, title, body and
footer. Plain-text command replies are promoted to the same panel automatically.

Classic interactive views are deliberately preserved as one native embed because a
legacy ``discord.ui.View`` cannot be mixed with a ``LayoutView`` in the same message.
Logs and ordinary ``TextChannel.send`` calls are never patched here.
"""
from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from . import command_visuals as visuals

logger = logging.getLogger("bot.unified-command-panels")

_INSTALLED = False
_PREVIOUS_CONTEXT_SEND = None
_PREVIOUS_INTERACTION_SEND = None
_PREVIOUS_WEBHOOK_SEND = None
_RAW_CONTEXT_SEND = None
_RAW_INTERACTION_SEND = None
_RAW_WEBHOOK_SEND = None

_NATIVE_COMMAND_EXCEPTIONS = {"help", "setup", "profile", "me"}


def _unwrap_send(func):
    """Reach the Discord transport below SentriX presentation wrappers."""
    seen: set[int] = set()
    current = func
    while callable(current) and id(current) not in seen:
        seen.add(id(current))
        next_func = None
        for attr in (
            "_sentrix_original_send",
            "_sentrix_original",
            "_sentrix_previous_context_send",
            "_sentrix_previous_send",
        ):
            candidate = getattr(current, attr, None)
            if callable(candidate) and candidate is not current:
                next_func = candidate
                break
        if next_func is None:
            break
        current = next_func
    return current


def _root_command_name(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    root = getattr(command, "root_parent", None) or command
    return str(getattr(root, "name", "") or "").casefold()


def _interaction_command_name(interaction: discord.Interaction | None) -> str:
    command = getattr(interaction, "command", None) if interaction else None
    qualified = getattr(command, "qualified_name", None) or getattr(command, "name", None)
    return str(qualified or "SentriX").replace("-", " ").replace("_", " ").strip().title() or "SentriX"


def _semantic(embed: discord.Embed) -> discord.Embed:
    """Clone an embed and remove only a legacy SentriX command banner image."""
    try:
        return visuals._semantic_embed(embed)
    except Exception:
        clone = embed.copy()
        image_url = getattr(getattr(clone, "image", None), "url", None)
        if visuals._is_command_banner(image_url):
            clone.set_image(url=None)
        return clone


def _is_banner_only(embed: discord.Embed) -> bool:
    image_url = getattr(getattr(embed, "image", None), "url", None)
    if not visuals._is_command_banner(image_url):
        return False
    return not any(
        (
            getattr(embed, "title", None),
            getattr(embed, "description", None),
            getattr(getattr(embed, "author", None), "name", None),
            getattr(getattr(embed, "footer", None), "text", None),
            getattr(getattr(embed, "thumbnail", None), "url", None),
            getattr(embed, "fields", None),
        )
    )


def _extract_embed(kwargs: dict[str, Any]) -> tuple[discord.Embed | None, bool]:
    """Return one semantic embed and whether the payload can be collapsed safely."""
    single = kwargs.get("embed")
    if isinstance(single, discord.Embed):
        return _semantic(single), True

    values = kwargs.get("embeds")
    if not isinstance(values, (list, tuple)):
        return None, True

    semantic: list[discord.Embed] = []
    for item in values:
        if not isinstance(item, discord.Embed):
            continue
        if _is_banner_only(item):
            continue
        semantic.append(_semantic(item))

    if len(semantic) == 1:
        return semantic[0], True
    if not semantic:
        return None, True
    return None, False


def _native_one_card_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Remove image-only banner embeds while preserving classic interactive payloads."""
    output = dict(kwargs)
    embed, collapsible = _extract_embed(output)
    if collapsible and embed is not None:
        output.pop("embeds", None)
        output["embed"] = embed
    elif collapsible and isinstance(output.get("embeds"), (list, tuple)):
        output["embeds"] = [
            _semantic(item)
            for item in output["embeds"]
            if isinstance(item, discord.Embed) and not _is_banner_only(item)
        ]
    return output


def _small_separator() -> discord.ui.Separator:
    spacing_enum = getattr(discord, "SeparatorSpacing", None)
    small = getattr(spacing_enum, "small", None) if spacing_enum is not None else None
    if small is not None:
        try:
            return discord.ui.Separator(spacing=small)
        except (TypeError, ValueError):
            pass
    return discord.ui.Separator()


def _clean(value: object, *, limit: int) -> str:
    try:
        return visuals._clean_text(value, limit=limit)
    except Exception:
        text = str(value or "").strip()
        return text[:limit]


def _fields(embed: discord.Embed | None) -> str:
    if embed is None:
        return ""
    try:
        return visuals._compact_fields(embed)
    except Exception:
        blocks = []
        for field in embed.fields:
            name = _clean(field.name, limit=80)
            value = _clean(field.value, limit=900)
            if name and value:
                blocks.append(f"**{name}**\n{value}")
        return "\n\n".join(blocks)[:3000]


class UnifiedCommandPanel(discord.ui.LayoutView):
    """One wide Components V2 card for one SentriX command response."""

    def __init__(
        self,
        *,
        title_fallback: str,
        content: object = None,
        embed: discord.Embed | None = None,
        kind: str = "info",
    ) -> None:
        super().__init__(timeout=None)

        accent = int(getattr(getattr(embed, "colour", None), "value", 0) or visuals._ACCENTS.get(kind, 0x3B82F6))
        container = discord.ui.Container(accent_colour=discord.Colour(accent))

        # Banner + body live in the SAME container. This is the key invariant: never
        # create a second Discord embed solely to display the SentriX banner.
        gallery = discord.ui.MediaGallery()
        gallery.add_item(media=visuals.banner_url(kind))
        container.add_item(gallery)

        title = _clean(getattr(embed, "title", None) if embed else None, limit=220) or title_fallback or "SentriX"
        header = f"## {title}"
        thumbnail = str(getattr(getattr(embed, "thumbnail", None), "url", None) or "") if embed else ""
        if thumbnail:
            try:
                container.add_item(
                    discord.ui.Section(
                        discord.ui.TextDisplay(header),
                        accessory=discord.ui.Thumbnail(thumbnail),
                    )
                )
            except Exception:
                container.add_item(discord.ui.TextDisplay(header))
        else:
            container.add_item(discord.ui.TextDisplay(header))

        description = _clean(getattr(embed, "description", None) if embed else content, limit=2600)
        field_text = _fields(embed)
        body = "\n\n".join(part for part in (description, field_text) if part).strip()
        if body:
            container.add_item(_small_separator())
            container.add_item(discord.ui.TextDisplay(body[:3900]))

        image_url = str(getattr(getattr(embed, "image", None), "url", None) or "") if embed else ""
        if image_url and not visuals._is_command_banner(image_url):
            try:
                media = discord.ui.MediaGallery()
                media.add_item(media=image_url)
                container.add_item(media)
            except Exception:
                logger.debug("Impossible d'ajouter l'image métier au panneau commande.", exc_info=True)

        footer = _clean(getattr(getattr(embed, "footer", None), "text", None), limit=260) if embed else ""
        footer = footer or "SentriX"
        container.add_item(_small_separator())
        container.add_item(discord.ui.TextDisplay(f"-# {footer}"))
        self.add_item(container)


def _incompatible(kwargs: dict[str, Any], *, content: object, embed: discord.Embed | None, collapsible: bool) -> bool:
    view = kwargs.get("view")
    if view is not None:
        return True
    if not collapsible:
        return True
    if content is not None and embed is not None:
        # Content alongside an embed often carries a real mention/ping; preserve it.
        return True
    return any(
        kwargs.get(key) is not None
        for key in ("file", "files", "poll", "stickers")
    )


async def _context_send(self: commands.Context, *args: Any, **kwargs: Any):
    assert _PREVIOUS_CONTEXT_SEND is not None

    if kwargs.get("_sentrix_native", False) or getattr(self, "command", None) is None:
        return await _PREVIOUS_CONTEXT_SEND(self, *args, **kwargs)

    if _root_command_name(self) in _NATIVE_COMMAND_EXCEPTIONS:
        return await _PREVIOUS_CONTEXT_SEND(self, *args, **kwargs)

    content = args[0] if args else kwargs.get("content")
    embed, collapsible = _extract_embed(kwargs)

    if _incompatible(kwargs, content=content, embed=embed, collapsible=collapsible):
        # Even in native mode, collapse the legacy [banner embed, body embed] pair to one
        # real embed. This keeps classic button views functional without the double card.
        output = _native_one_card_kwargs(kwargs)
        raw = _RAW_CONTEXT_SEND or _PREVIOUS_CONTEXT_SEND
        if args:
            output.pop("content", None)
            return await raw(self, content, **output)
        return await raw(self, **output)

    if embed is None and content is None:
        return await _PREVIOUS_CONTEXT_SEND(self, *args, **kwargs)

    kind = visuals.resolve_kind(self, embed=embed, content=content)
    layout = UnifiedCommandPanel(
        title_fallback=visuals._human_command_name(self),
        content=content,
        embed=embed,
        kind=kind,
    )

    output = dict(kwargs)
    output.pop("content", None)
    output.pop("embed", None)
    output.pop("embeds", None)
    output["view"] = layout
    output.pop("_sentrix_native", None)

    raw = _RAW_CONTEXT_SEND or _PREVIOUS_CONTEXT_SEND
    return await raw(self, None, **output)


async def _interaction_send(self, *args: Any, **kwargs: Any):
    assert _PREVIOUS_INTERACTION_SEND is not None

    interaction = getattr(self, "_parent", None)
    if getattr(interaction, "type", None) is not discord.InteractionType.application_command:
        return await _PREVIOUS_INTERACTION_SEND(self, *args, **kwargs)

    content = args[0] if args else kwargs.get("content")
    embed, collapsible = _extract_embed(kwargs)
    raw = _RAW_INTERACTION_SEND or _PREVIOUS_INTERACTION_SEND

    if _incompatible(kwargs, content=content, embed=embed, collapsible=collapsible):
        output = _native_one_card_kwargs(kwargs)
        if args:
            output.pop("content", None)
            return await raw(self, content, **output)
        return await raw(self, **output)

    if embed is None and content is None:
        return await _PREVIOUS_INTERACTION_SEND(self, *args, **kwargs)

    kind = visuals.resolve_kind(None, embed=embed, content=content)
    layout = UnifiedCommandPanel(
        title_fallback=_interaction_command_name(interaction),
        content=content,
        embed=embed,
        kind=kind,
    )
    output = dict(kwargs)
    output.pop("content", None)
    output.pop("embed", None)
    output.pop("embeds", None)
    output["view"] = layout
    return await raw(self, None, **output)


async def _webhook_send(self, *args: Any, **kwargs: Any):
    assert _PREVIOUS_WEBHOOK_SEND is not None

    # Application webhooks are interaction followups. Ordinary webhooks (including log
    # transports/integrations) are never touched.
    if getattr(self, "type", None) is not discord.WebhookType.application:
        return await _PREVIOUS_WEBHOOK_SEND(self, *args, **kwargs)

    content = args[0] if args else kwargs.get("content")
    embed, collapsible = _extract_embed(kwargs)
    raw = _RAW_WEBHOOK_SEND or _PREVIOUS_WEBHOOK_SEND

    if _incompatible(kwargs, content=content, embed=embed, collapsible=collapsible):
        output = _native_one_card_kwargs(kwargs)
        if args:
            output.pop("content", None)
            return await raw(self, content, **output)
        return await raw(self, **output)

    if embed is None and content is None:
        return await _PREVIOUS_WEBHOOK_SEND(self, *args, **kwargs)

    kind = visuals.resolve_kind(None, embed=embed, content=content)
    layout = UnifiedCommandPanel(
        title_fallback=(getattr(embed, "title", None) or "SentriX") if embed else "SentriX",
        content=content,
        embed=embed,
        kind=kind,
    )
    output = dict(kwargs)
    output.pop("content", None)
    output.pop("embed", None)
    output.pop("embeds", None)
    output["view"] = layout
    return await raw(self, None, **output)


def install_unified_command_panels() -> None:
    """Install the final command transport once, after legacy compatibility layers."""
    global _INSTALLED
    global _PREVIOUS_CONTEXT_SEND, _PREVIOUS_INTERACTION_SEND, _PREVIOUS_WEBHOOK_SEND
    global _RAW_CONTEXT_SEND, _RAW_INTERACTION_SEND, _RAW_WEBHOOK_SEND

    if _INSTALLED:
        return
    _INSTALLED = True

    current_context = commands.Context.send
    _PREVIOUS_CONTEXT_SEND = current_context
    _RAW_CONTEXT_SEND = getattr(visuals, "_ORIGINAL_CONTEXT_SEND", None) or _unwrap_send(current_context)
    if not getattr(current_context, "_sentrix_unified_command_panels", False):
        _context_send._sentrix_unified_command_panels = True
        _context_send._sentrix_previous_context_send = current_context
        commands.Context.send = _context_send

    current_interaction = discord.InteractionResponse.send_message
    _PREVIOUS_INTERACTION_SEND = current_interaction
    _RAW_INTERACTION_SEND = _unwrap_send(current_interaction)
    if not getattr(current_interaction, "_sentrix_unified_command_panels", False):
        _interaction_send._sentrix_unified_command_panels = True
        _interaction_send._sentrix_original = current_interaction
        discord.InteractionResponse.send_message = _interaction_send

    current_webhook = discord.Webhook.send
    _PREVIOUS_WEBHOOK_SEND = current_webhook
    _RAW_WEBHOOK_SEND = _unwrap_send(current_webhook)
    if not getattr(current_webhook, "_sentrix_unified_command_panels", False):
        _webhook_send._sentrix_unified_command_panels = True
        _webhook_send._sentrix_original = current_webhook
        discord.Webhook.send = _webhook_send

    logger.info("Rendu commandes unifié : un panneau V2 par réponse simple, texte brut inclus.")


__all__ = ["UnifiedCommandPanel", "install_unified_command_panels"]
