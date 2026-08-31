"""Large visual presentation for SentriX command responses.

This module only styles ``commands.Context.send`` responses. It never touches
``TextChannel.send`` / ``Messageable.send`` and therefore cannot intercept the
Components V2 log transport.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import discord
from discord.ext import commands

from . import embeds
from .log_banners import BANNER_DIR, ensure_banners

logger = logging.getLogger("bot.command-visuals")

_BANNER_RAW_BASE = (
    "https://raw.githubusercontent.com/eventore4567/mon-bot-discord/"
    "main/assets/log_banners"
)
_BANNER_URLS = {
    "error": f"{_BANNER_RAW_BASE}/banner_source_error.webp",
    "success": f"{_BANNER_RAW_BASE}/banner_source_success.webp",
    "warning": f"{_BANNER_RAW_BASE}/banner_source_warning.webp",
    "info": f"{_BANNER_RAW_BASE}/banner_source_info.webp",
    "special": f"{_BANNER_RAW_BASE}/banner_source_special.webp",
}
_ACCENTS = {
    "error": 0xEF4444,
    "success": 0x22C55E,
    "warning": 0xF59E0B,
    "info": 0x3B82F6,
    "special": 0x7C3AED,
}

_DECORATIVE_LINE_RE = re.compile(r"^[\s━─═—–_\-•·┄┈┉┅┇]{8,}$")
_COMMAND_BANNER_RE = re.compile(r"/banner_source_(?:error|success|warning|info|special)\.webp(?:\?.*)?$")

_ERROR_WORDS = (
    "erreur", "impossible", "introuvable", "interdit", "refus", "échou", "echec",
    "échec", "banni", "bannissement", "supprim", "expuls", "kick", "sanction",
)
_SUCCESS_WORDS = (
    "succès", "succes", "effectué", "effectue", "réussi", "reussi", "créé", "cree",
    "ajouté", "ajoute", "activé", "active", "enregistré", "enregistre", "terminé",
    "termine", "restauré", "restaure",
)
_WARNING_WORDS = (
    "attention", "avert", "cooldown", "recharge", "attendre", "limite", "vérification",
    "verification", "permission requise",
)

_ERROR_COGS = {"moderation", "automod", "security", "securitytools"}
_WARNING_COGS = {"tickets", "configuration", "serverbuilder", "verification"}
_SUCCESS_COGS = {"economy", "levels", "invites"}
_SPECIAL_COGS = {"ai", "minigames", "gameseconomy", "music", "events", "design"}

_INSTALLED = False
_ORIGINAL_CONTEXT_SEND = None
_ORIGINAL_EMBED_BASE = None


def _clean_text(value: object, *, limit: int = 3500) -> str:
    lines: list[str] = []
    for raw in str(value or "").replace("\r", "").splitlines():
        stripped = raw.strip()
        if stripped and _DECORATIVE_LINE_RE.fullmatch(stripped):
            continue
        lines.append(raw.rstrip())
    text = "\n".join(lines).strip()
    if len(text) > limit:
        text = text[: max(1, limit - 1)].rstrip() + "…"
    return text


def _human_command_name(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    qualified = getattr(command, "qualified_name", None) or getattr(ctx, "invoked_with", None) or "SentriX"
    return str(qualified).replace("-", " ").replace("_", " ").strip().title() or "SentriX"


def _cog_key(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    cog_name = getattr(command, "cog_name", None) or getattr(getattr(ctx, "cog", None), "qualified_name", None) or ""
    return re.sub(r"[^a-z]", "", str(cog_name).casefold())


def _kind_from_text(text: str) -> str | None:
    folded = text.casefold()
    if any(word in folded for word in _ERROR_WORDS):
        return "error"
    if any(word in folded for word in _WARNING_WORDS):
        return "warning"
    if any(word in folded for word in _SUCCESS_WORDS):
        return "success"
    return None


def _kind_from_colour(colour: discord.Colour | None) -> str | None:
    if colour is None:
        return None
    value = int(getattr(colour, "value", 0) or 0)
    if value in {0xEF4444, 0xED4245, 0xFF4155}:
        return "error"
    if value in {0x22C55E, 0x57F287, 0x2DDD77}:
        return "success"
    if value in {0xF59E0B, 0xFEE75C, 0xFFB937}:
        return "warning"
    if value in {0x3B82F6, 0x3498DB, 0x3797FF}:
        return "info"
    if value in {0x7C3AED, 0x9B59B6, 0xAE61FF}:
        return "special"
    return None


def resolve_kind(
    ctx: commands.Context | None,
    *,
    embed: discord.Embed | None = None,
    content: object = None,
) -> str:
    title = getattr(embed, "title", "") if embed else ""
    description = getattr(embed, "description", "") if embed else ""
    detected = _kind_from_text(f"{title or ''} {description or ''} {content or ''}")
    if detected:
        return detected

    colour_kind = _kind_from_colour(getattr(embed, "colour", None) if embed else None)
    if colour_kind:
        return colour_kind

    if ctx is not None:
        cog = _cog_key(ctx)
        if cog in _ERROR_COGS:
            return "error"
        if cog in _WARNING_COGS:
            return "warning"
        if cog in _SUCCESS_COGS:
            return "success"
        if cog in _SPECIAL_COGS:
            return "special"
    return "info"


def banner_url(kind: str) -> str:
    return _BANNER_URLS.get(kind, _BANNER_URLS["info"])


def _is_command_banner(url: object) -> bool:
    return bool(_COMMAND_BANNER_RE.search(str(url or "")))


def _decorate_embed(embed: discord.Embed, kind: str) -> discord.Embed:
    """Add the command banner without replacing a semantic image."""
    result = embed.copy()
    current_image = getattr(getattr(result, "image", None), "url", None)
    if not current_image or _is_command_banner(current_image):
        result.set_image(url=banner_url(kind))
    return result


def _small_separator() -> discord.ui.Separator:
    spacing_enum = getattr(discord, "SeparatorSpacing", None)
    small = getattr(spacing_enum, "small", None) if spacing_enum is not None else None
    if small is not None:
        try:
            return discord.ui.Separator(spacing=small)
        except (TypeError, ValueError):
            pass
    return discord.ui.Separator()


def _compact_fields(embed: discord.Embed) -> str:
    small: list[str] = []
    blocks: list[str] = []

    def flush() -> None:
        nonlocal small
        if small:
            blocks.append("  ·  ".join(small))
            small = []

    for field in embed.fields:
        name = _clean_text(field.name, limit=80)
        value = _clean_text(field.value, limit=1000)
        if not name or not value:
            continue

        if len(value) <= 70 and "\n" not in value and len(name) <= 32:
            small.append(f"**{name} :** {value}")
            if len(small) == 4:
                flush()
        else:
            flush()
            quote = value.replace("\n", "\n> ")
            blocks.append(f"**{name}**\n>>> {quote}")

    flush()
    return "\n\n".join(blocks)[:3000]


class CommandPanelView(discord.ui.LayoutView):
    """Wide Components V2 card used by ordinary command responses."""

    def __init__(
        self,
        ctx: commands.Context,
        *,
        content: object = None,
        embed: discord.Embed | None = None,
        kind: str = "info",
        banner_filename: str,
    ) -> None:
        super().__init__(timeout=None)

        accent = getattr(getattr(embed, "colour", None), "value", None) if embed else None
        if not accent:
            accent = _ACCENTS[kind]
        container = discord.ui.Container(accent_colour=discord.Colour(int(accent)))

        gallery = discord.ui.MediaGallery()
        gallery.add_item(media=f"attachment://{banner_filename}")
        container.add_item(gallery)

        title = _clean_text(getattr(embed, "title", None) if embed else None, limit=220)
        if not title:
            title = _human_command_name(ctx)

        thumbnail = getattr(getattr(embed, "thumbnail", None), "url", None) if embed else None
        header = f"## {title}"
        if thumbnail:
            try:
                container.add_item(
                    discord.ui.Section(
                        discord.ui.TextDisplay(header),
                        accessory=discord.ui.Thumbnail(str(thumbnail)),
                    )
                )
            except Exception:
                logger.exception("COMMAND V2 thumbnail fallback command=%s", _human_command_name(ctx))
                container.add_item(discord.ui.TextDisplay(header))
        else:
            container.add_item(discord.ui.TextDisplay(header))

        description = _clean_text(getattr(embed, "description", None) if embed else content, limit=2600)
        fields = _compact_fields(embed) if embed else ""
        body_parts = [part for part in (description, fields) if part]
        body = "\n\n".join(body_parts).strip()

        if body:
            container.add_item(_small_separator())
            container.add_item(discord.ui.TextDisplay(body[:3900]))

        image_url = getattr(getattr(embed, "image", None), "url", None) if embed else None
        if image_url and not _is_command_banner(image_url):
            try:
                media = discord.ui.MediaGallery()
                media.add_item(media=str(image_url))
                container.add_item(media)
            except Exception:
                logger.exception("COMMAND V2 media fallback command=%s", _human_command_name(ctx))

        footer = _clean_text(getattr(getattr(embed, "footer", None), "text", None), limit=300) if embed else ""
        if not footer:
            footer = "SentriX"
        container.add_item(_small_separator())
        container.add_item(discord.ui.TextDisplay(f"-# {footer}"))

        self.add_item(container)


def _native_payload(
    ctx: commands.Context,
    content: object,
    embed: discord.Embed | None,
    kwargs: dict[str, Any],
) -> tuple[object, dict[str, Any]]:
    """Keep interactive/native messages intact, only adding the banner."""
    kind = resolve_kind(ctx, embed=embed, content=content)
    output = dict(kwargs)

    if embed is not None:
        output["embed"] = _decorate_embed(embed, kind)
        return content, output

    if content is not None:
        panel = discord.Embed(
            title=_human_command_name(ctx),
            description=_clean_text(content, limit=3900) or None,
            colour=discord.Colour(_ACCENTS[kind]),
        )
        panel.set_image(url=banner_url(kind))
        output["embed"] = panel
        return None, output

    return content, output


async def _styled_context_send(self: commands.Context, *args: Any, **kwargs: Any):
    """Large command renderer; never intercepts direct channel/log sends."""
    assert _ORIGINAL_CONTEXT_SEND is not None

    if kwargs.pop("_sentrix_native", False):
        return await _ORIGINAL_CONTEXT_SEND(self, *args, **kwargs)

    content = args[0] if args else kwargs.pop("content", None)
    embed = kwargs.get("embed")
    if embed is not None and not isinstance(embed, discord.Embed):
        return await _ORIGINAL_CONTEXT_SEND(self, content, **kwargs)

    command = getattr(self, "command", None)
    root = getattr(command, "root_parent", None) or command
    command_name = str(getattr(root, "name", "") or "").casefold()
    view = kwargs.get("view")

    # +help and +setup keep their exact classic structure. Interactive classic views also
    # stay native so their existing edit_message(embed=..., view=...) callbacks keep working.
    keep_native = (
        command_name in {"help", "setup"}
        or (view is not None and not isinstance(view, discord.ui.LayoutView))
        or kwargs.get("poll") is not None
        or kwargs.get("file") is not None
        or kwargs.get("files") is not None
        or kwargs.get("embeds") is not None
        or kwargs.get("stickers") is not None
    )

    if keep_native:
        native_content, native_kwargs = _native_payload(self, content, embed, kwargs)
        return await _ORIGINAL_CONTEXT_SEND(self, native_content, **native_kwargs)

    kind = resolve_kind(self, embed=embed, content=content)
    ensure_banners()
    banner_path = BANNER_DIR / f"banner_{kind}.png"
    if not banner_path.exists():
        ensure_banners(force=True)

    banner_filename = f"sentrix_command_{kind}.png"
    try:
        layout = CommandPanelView(
            self,
            content=content,
            embed=embed,
            kind=kind,
            banner_filename=banner_filename,
        )
        banner_file = discord.File(str(banner_path), filename=banner_filename)
    except Exception:
        logger.exception("COMMAND V2 build failed command=%s; native fallback", _human_command_name(self))
        native_content, native_kwargs = _native_payload(self, content, embed, kwargs)
        return await _ORIGINAL_CONTEXT_SEND(self, native_content, **native_kwargs)

    output = dict(kwargs)
    output.pop("embed", None)
    output.pop("content", None)
    output["view"] = layout
    output["file"] = banner_file

    try:
        return await _ORIGINAL_CONTEXT_SEND(self, None, **output)
    except discord.HTTPException:
        logger.exception("COMMAND V2 send failed command=%s; native fallback", _human_command_name(self))
        try:
            banner_file.close()
        except Exception:
            pass
        native_content, native_kwargs = _native_payload(self, content, embed, kwargs)
        return await _ORIGINAL_CONTEXT_SEND(self, native_content, **native_kwargs)


def _install_embed_banner_factory() -> None:
    global _ORIGINAL_EMBED_BASE
    original = getattr(embeds, "_base", None)
    if original is None or getattr(original, "_sentrix_command_banner", False):
        return

    _ORIGINAL_EMBED_BASE = original

    def branded_base(*args: Any, **kwargs: Any) -> discord.Embed:
        # Disable the old single-image banner path, then apply the new thin banner
        # according to the actual result (error/success/warning/info/brand).
        kwargs["banner"] = False
        result = original(*args, **kwargs)
        text = f"{getattr(result, 'title', '') or ''} {getattr(result, 'description', '') or ''}"
        kind = _kind_from_text(text)
        if kind is None:
            requested_kind = str(kwargs.get("kind") or "").casefold()
            kind = {
                "danger": "error",
                "error": "error",
                "success": "success",
                "warning": "warning",
                "info": "info",
                "neutral": "info",
                "brand": "special",
                "special": "special",
            }.get(requested_kind)
        if kind is None:
            kind = _kind_from_colour(getattr(result, "colour", None)) or "special"

        current_image = getattr(getattr(result, "image", None), "url", None)
        if not current_image:
            result.set_image(url=banner_url(kind))
        return result

    branded_base._sentrix_command_banner = True
    embeds._base = branded_base


def install_command_visuals() -> None:
    """Install the command-only presentation layer once."""
    global _INSTALLED, _ORIGINAL_CONTEXT_SEND
    if _INSTALLED:
        return
    _INSTALLED = True

    _install_embed_banner_factory()

    original_send = commands.Context.send
    if not getattr(original_send, "_sentrix_command_visuals", False):
        _ORIGINAL_CONTEXT_SEND = original_send
        _styled_context_send._sentrix_command_visuals = True
        _styled_context_send._sentrix_original_send = original_send
        commands.Context.send = _styled_context_send
        logger.info("Command visuals installed: wide V2 + thin SentriX banners")
    else:
        _ORIGINAL_CONTEXT_SEND = getattr(original_send, "_sentrix_original_send", original_send)


__all__ = [
    "CommandPanelView",
    "banner_url",
    "install_command_visuals",
    "resolve_kind",
]
