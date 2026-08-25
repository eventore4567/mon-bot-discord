"""Politique visuelle canonique des réponses de commandes SentriX.

Le renderer de base est appelé une seule fois. Cette couche impose ensuite le contrat final
compact/panneau et retire les emojis décoratifs des interfaces de commandes. Les logs et le
texte libre saisi par les utilisateurs ne sont pas modifiés.
"""
from __future__ import annotations

import re
from typing import Any

import discord

from utils import premium_style

_MANY_BLANKS_RE = re.compile(r"\n{3,}")
_MARKDOWN_RE = re.compile(r"[*_`~>|#]+")
_DECORATIVE_TITLE_RE = re.compile(r"^[\s\u200b]*(?:[^\wÀ-ÿ]{1,4}\s*)+")
_SPACE_RE = re.compile(r"\s+")
_CANONICAL_TITLE_RE = re.compile(r"^(?:SentriX|Odboug)\s*•\s*(.+)$", re.IGNORECASE)
_LEADING_DETAIL_RE = re.compile(r"^\*\*(.{1,96}?)\*\*(?:\n+|$)")
_CUSTOM_EMOJI_RE = re.compile(r"<a?:[A-Za-z0-9_]{2,32}:[0-9]+>")
_ZWSP = "\u200b"

COMPACT_DESCRIPTION_LIMIT = 360
PANEL_DESCRIPTION_LIMIT = 900
COMPACT_FIELD_LIMIT = 220
PANEL_FIELD_LIMIT = 520
COMPACT_TITLE_LIMIT = 42
PANEL_TITLE_LIMIT = 52

_GENERIC_STATE_TITLES = {
    "success": "Action réussie", "warning": "À vérifier",
    "danger": "Action impossible", "info": "Information",
}
_GENERIC_FIELDS = {
    "information", "informations", "details", "détails", "detail", "détail",
    "resume", "résumé", "aperçu", "apercu", "description", "etat", "état",
}


def _is_emoji_char(char: str) -> bool:
    code = ord(char)
    return (
        0x1F000 <= code <= 0x1FAFF
        or 0x2600 <= code <= 0x27BF
        or 0x2300 <= code <= 0x23FF
        or 0x1F1E6 <= code <= 0x1F1FF
        or code in {0x200D, 0xFE0F, 0x20E3}
    )


def strip_interface_emojis(value: Any) -> str:
    """Retire uniquement la décoration emoji d'un libellé d'interface."""
    text = _CUSTOM_EMOJI_RE.sub("", str(value or ""))
    text = "".join(char for char in text if not _is_emoji_char(char))
    return _SPACE_RE.sub(" ", text).strip()


def _semantic(value: Any) -> str:
    text = str(value or "").replace(_ZWSP, " ")
    text = _CANONICAL_TITLE_RE.sub(r"\1", text)
    text = _DECORATIVE_TITLE_RE.sub("", text)
    text = _MARKDOWN_RE.sub("", text)
    text = re.sub(r"[^\wÀ-ÿ]+", " ", text, flags=re.UNICODE)
    return _SPACE_RE.sub(" ", text).strip().casefold()


def _clean_block(value: Any, *, limit: int = 4096) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = _MANY_BLANKS_RE.sub("\n\n", text)
    return premium_style.clip(text, limit)


def _dedupe_blocks(value: Any) -> str | None:
    text = _clean_block(value)
    if not text:
        return None
    seen: set[str] = set()
    kept: list[str] = []
    for block in (part.strip() for part in re.split(r"\n\s*\n", text)):
        if not block:
            continue
        key = _semantic(block)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        kept.append(block)
    return "\n\n".join(kept) or None


def _title(value: Any, fallback: str = "Information", *, limit: int = PANEL_TITLE_LIMIT) -> str:
    text = premium_style.clean_title(value, fallback=fallback)
    text = strip_interface_emojis(_DECORATIVE_TITLE_RE.sub("", text).strip())
    return premium_style.clip(text or fallback, limit)


def _promote_useful_title(embed: discord.Embed, *, kind: str) -> None:
    current = str(embed.title or "").strip()
    description = _dedupe_blocks(embed.description)
    canonical = _CANONICAL_TITLE_RE.match(current)
    if canonical is None:
        if current:
            embed.title = _title(current)
        embed.description = description
        return
    detail = _LEADING_DETAIL_RE.match(description or "")
    if detail:
        embed.title = _title(detail.group(1))
        embed.description = (description or "")[detail.end():].lstrip() or None
        return
    embed.title = _title(canonical.group(1)) if kind == "info" else _GENERIC_STATE_TITLES.get(kind, "Information")
    embed.description = description


def _refine_fields(embed: discord.Embed) -> None:
    description_key = _semantic(embed.description)
    title_key = _semantic(embed.title)
    seen: set[tuple[str, str]] = set()
    output: list[tuple[str, str, bool]] = []
    for field in list(embed.fields):
        name = premium_style.display_label(field.name, "Information")
        name = strip_interface_emojis(name) or "Information"
        value = _dedupe_blocks(field.value) or "—"
        name_key, value_key = _semantic(name), _semantic(value)
        if not name_key and not value_key:
            continue
        if name_key in _GENERIC_FIELDS and value_key == description_key:
            continue
        if name_key == title_key and value_key == description_key:
            continue
        signature = (name_key, value_key)
        if signature in seen:
            continue
        seen.add(signature)
        output.append((premium_style.clip(name, 256), premium_style.clip(value, 1024), bool(field.inline)))
    embed.clear_fields()
    for name, value, inline in output:
        embed.add_field(name=name, value=value, inline=inline)


def layout_size(embed: discord.Embed) -> str:
    description = str(embed.description or "")
    fields = list(embed.fields)
    image = str(getattr(getattr(embed, "image", None), "url", "") or "")
    thumbnail = str(getattr(getattr(embed, "thumbnail", None), "url", "") or "")
    if image or thumbnail or len(fields) >= 3 or len(description) > COMPACT_DESCRIPTION_LIMIT:
        return "panel"
    if len(fields) == 2 and sum(len(str(field.value or "")) for field in fields) > 320:
        return "panel"
    return "compact"


def _apply_layout(embed: discord.Embed, size: str) -> None:
    compact = size == "compact"
    title_limit = COMPACT_TITLE_LIMIT if compact else PANEL_TITLE_LIMIT
    description_limit = COMPACT_DESCRIPTION_LIMIT if compact else PANEL_DESCRIPTION_LIMIT
    field_limit = COMPACT_FIELD_LIMIT if compact else PANEL_FIELD_LIMIT
    field_count = 2 if compact else 6
    if embed.title:
        embed.title = premium_style.clip(strip_interface_emojis(embed.title), title_limit)
    embed.description = _clean_block(embed.description, limit=description_limit)
    output: list[tuple[str, str, bool]] = []
    for field in list(embed.fields)[:field_count]:
        name = premium_style.clip(strip_interface_emojis(field.name), 64) or "Information"
        value = _clean_block(field.value, limit=field_limit) or "—"
        inline = False if compact else bool(
            field.inline and len(value) <= 105 and value.count("\n") <= 1
            and "```" not in value and len(name) <= 28
        )
        output.append((name, value, inline))
    embed.clear_fields()
    for name, value, inline in output:
        embed.add_field(name=name, value=value, inline=inline)


def _canonical_author_footer(embed: discord.Embed, *, bot_user: Any, guild: discord.Guild | None, size: str) -> None:
    brand = premium_style.CATEGORY_NAMES.get("brand", "SentriX")
    if size == "compact":
        embed.remove_author()
    else:
        current = str(getattr(getattr(embed, "author", None), "name", "") or "").strip()
        if not current or current.casefold().startswith(("sentrix", "odboug")):
            avatar = getattr(getattr(bot_user, "display_avatar", None), "url", None)
            if avatar:
                embed.set_author(name=brand, icon_url=str(avatar))
            else:
                embed.set_author(name=brand)

    current_footer = str(getattr(getattr(embed, "footer", None), "text", "") or "").strip()
    footer_icon = getattr(getattr(embed, "footer", None), "icon_url", None)
    if current_footer and not any(token in current_footer.casefold() for token in ("sentrix", "odboug", "page ")):
        return
    parts = [brand]
    if guild is not None:
        name = premium_style.clip(getattr(guild, "name", "Serveur"), 42)
        if name:
            parts.append(name)
    footer = " • ".join(parts)
    if footer_icon:
        embed.set_footer(text=footer, icon_url=footer_icon)
    else:
        embed.set_footer(text=footer)


def _refine_after_base(
    result: discord.Embed,
    *,
    command: Any = None,
    guild: discord.Guild | None = None,
    bot_user: Any = None,
    category: str | None = None,
    kind: str | None = None,
    log_type: str | None = None,
) -> discord.Embed:
    resolved_category = premium_style.infer_category(command=command, embed=result, hint=category)
    if log_type or resolved_category == "logs":
        return result
    resolved_kind = kind or premium_style.infer_kind(result)
    _promote_useful_title(result, kind=resolved_kind)
    _refine_fields(result)
    result.description = _dedupe_blocks(result.description)
    result.timestamp = None
    size = layout_size(result)
    _apply_layout(result, size)
    _canonical_author_footer(result, bot_user=bot_user, guild=guild, size=size)
    return result


def style_embed(
    embed: discord.Embed,
    *,
    command: Any = None,
    guild: discord.Guild | None = None,
    requester: Any = None,
    bot_user: Any = None,
    category: str | None = None,
    kind: str | None = None,
    log_type: str | None = None,
) -> discord.Embed:
    base = premium_style.style_embed(
        embed, command=command, guild=guild, requester=requester, bot_user=bot_user,
        category=category, kind=kind, log_type=log_type,
    )
    return _refine_after_base(
        base, command=command, guild=guild, bot_user=bot_user,
        category=category, kind=kind, log_type=log_type,
    )


def _refine_view_after_base(view: discord.ui.View | None) -> discord.ui.View | None:
    if view is None:
        return None
    for item in list(getattr(view, "children", ()) or ()):
        if isinstance(item, discord.ui.Button):
            # Les composants des commandes restent volontairement textuels.
            item.emoji = None
            if item.label:
                item.label = premium_style.clip(
                    strip_interface_emojis(item.label),
                    premium_style.VISUAL_LIMITS["button_label"],
                )
        elif isinstance(item, discord.ui.Select):
            item.placeholder = premium_style.clip(
                strip_interface_emojis(item.placeholder or "Choisis une option…") or "Choisis une option…",
                premium_style.VISUAL_LIMITS["select_label"],
            )
            for option in list(getattr(item, "options", ()) or ()):
                option.emoji = None
                option.label = premium_style.clip(
                    strip_interface_emojis(option.label),
                    100,
                )
    return view


def style_view(view: discord.ui.View | None) -> discord.ui.View | None:
    return _refine_view_after_base(premium_style.style_view(view))


def style_kwargs(
    args: tuple[Any, ...], kwargs: dict[str, Any], *, command: Any = None,
    guild: discord.Guild | None = None, requester: Any = None, bot_user: Any = None,
    allow_content_wrap: bool = False, include_brand_asset: bool = False,
    category: str | None = None, log_type: str | None = None,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    args, output = premium_style.style_kwargs(
        args, kwargs, command=command, guild=guild, requester=requester, bot_user=bot_user,
        allow_content_wrap=allow_content_wrap, include_brand_asset=include_brand_asset,
        category=category, log_type=log_type,
    )
    if log_type:
        return args, output
    if isinstance(output.get("embed"), discord.Embed):
        output["embed"] = _refine_after_base(
            output["embed"], command=command, guild=guild, bot_user=bot_user, category=category,
        )
    if output.get("embeds"):
        output["embeds"] = [
            _refine_after_base(item, command=command, guild=guild, bot_user=bot_user, category=category)
            if isinstance(item, discord.Embed) else item
            for item in output["embeds"]
        ]
    if "view" in output:
        output["view"] = _refine_view_after_base(output.get("view"))
    return args, output


__all__ = ["style_embed", "style_view", "style_kwargs", "layout_size", "strip_interface_emojis"]
