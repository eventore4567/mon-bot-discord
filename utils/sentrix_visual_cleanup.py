"""Nettoyage visuel final de SentriX.

Cette couche s'installe après les renderers historiques :
- une seule grande ligne de séparation par commande, assez courte pour ne jamais déborder ;
- aucune barre de progression textuelle dans +ping ;
- journaux espacés et lisibles sans faux séparateurs répétés ;
- Avant / Après restent deux blocs Discord naturels.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable

import discord
from discord.ext import commands

from . import design_system
from . import embeds as sx
from . import premium_style
from . import sentrix_runtime as runtime

_INSTALLED = False

COLOR_INFO = runtime.COLOR_INFO
COLOR_SUCCESS = runtime.COLOR_SUCCESS
COLOR_WARNING = runtime.COLOR_WARNING
COLOR_MODIFICATION = runtime.COLOR_MODIFICATION
COLOR_DANGER = runtime.COLOR_DANGER
COLOR_SYSTEM = runtime.COLOR_SYSTEM
COLOR_NEUTRAL = runtime.COLOR_NEUTRAL

# Une seule ligne volontairement un peu plus courte que l'ancienne V6 : elle garde
# l'effet visuel large sans produire un petit reste de ━━━ sur la ligne suivante.
PANEL_BAR = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

_IDENTITY_FIELDS = {"membre", "auteur", "utilisateur", "cible"}
_BEFORE_FIELDS = {"avant", "ancienne valeur", "ancien"}
_AFTER_FIELDS = {"apres", "après", "nouvelle valeur", "nouveau"}

_SEPARATOR_LINE = re.compile(r"^[\s━─═—–_\-•·┄┈┉┅┇]+$")
_ORIGINAL_PREMIUM_STYLE_EMBED = premium_style.style_embed
_ORIGINAL_SX_STYLE_EXISTING = sx.style_existing


def _is_separator_line(line: str) -> bool:
    stripped = str(line or "").strip()
    return len(stripped) >= 4 and bool(_SEPARATOR_LINE.fullmatch(stripped))


def _clean_text(value: Any, limit: int = 4096) -> str:
    """Retire tous les anciens traits seuls et garde au maximum une ligne vide."""
    raw = str(value or "").replace("\r", "")
    lines = [line.rstrip() for line in raw.splitlines() if not _is_separator_line(line)]
    cleaned: list[str] = []
    blank = False
    for line in lines:
        if not line.strip():
            if cleaned and not blank:
                cleaned.append("")
            blank = True
            continue
        cleaned.append(line)
        blank = False
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()
    return sx.clip("\n".join(cleaned).strip(), limit)


def _command_text(value: Any, limit: int = 4096) -> str:
    """Normalise une commande vers exactement UNE séparation large et propre."""
    body = _clean_text(value, max(1, limit - len(PANEL_BAR) - 1))
    if body:
        return sx.clip(f"{PANEL_BAR}\n{body}", limit)
    return PANEL_BAR


def _one_line(value: Any, limit: int = 600) -> str:
    text = _clean_text(value, limit).replace("\n", " · ")
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return sx.clip(text, limit)


def _base_colour(title: str, description: str, colour: int | None, kind: str | None) -> int:
    explicit = str(kind or "").casefold()
    if explicit and explicit != "brand":
        return int(sx._colour(explicit, colour))
    if explicit == "brand":
        return int(colour or COLOR_SYSTEM)
    inferred = sx._kind_from_text(title, description)
    if inferred != "brand":
        return int(sx._colour(inferred, colour))
    return int(colour or COLOR_SYSTEM)


def _base(
    title: str,
    description: str | None = None,
    *,
    banner: bool = False,
    thumbnail: str | None = None,
    timestamp: bool = False,
    footer: str | None = None,
    colour: int | None = None,
    kind: str | None = None,
    clean_description: bool = True,
) -> discord.Embed:
    del banner
    safe_title = sx.clean_ui_text(title, 100, "Information")
    if clean_description:
        body = sx.clean_multiline_ui_text(description, 4096)
    else:
        body = sx.clip(description, 4096)
    clean_body = _clean_text(body, 4096)
    embed = discord.Embed(
        title=safe_title,
        description=_command_text(clean_body, 4096),
        colour=discord.Colour(_base_colour(safe_title, clean_body, colour, kind)),
        timestamp=datetime.now(timezone.utc) if timestamp else None,
    )
    if thumbnail:
        embed.set_thumbnail(url=str(thumbnail))
    return sx._footer(embed, footer)


def _design_create_embed(
    *,
    title: str,
    description: str | None = None,
    colour: int = design_system.COLORS.primary,
    user: discord.abc.User | None = None,
    thumbnail: str | None = None,
    footer: str | None = None,
) -> discord.Embed:
    footer_text = footer or (f"SentriX • demandé par {user}" if user else "SentriX")
    embed = _base(
        title,
        description,
        thumbnail=thumbnail,
        timestamp=True,
        footer=footer_text,
        colour=colour,
        kind="brand",
    )
    if user is not None:
        icon = str(getattr(getattr(user, "display_avatar", None), "url", "") or "")
        if icon:
            embed.set_footer(text=footer_text, icon_url=icon)
    return embed


def _coerce_fields(
    fields: Iterable[tuple[str, Any, bool | None] | tuple[str, Any]],
) -> list[tuple[str, str, bool | None]]:
    result: list[tuple[str, str, bool | None]] = []
    for item in fields:
        if len(item) == 2:
            name, value = item
            requested = None
        else:
            name, value, requested = item
        if value is None or not str(value).strip():
            continue
        safe_name = sx.clean_ui_text(name, 256, "Information")
        if safe_name.casefold() in getattr(sx, "_LEGACY_FILLER_FIELDS", set()):
            continue
        if getattr(sx, "_empty_log_value", lambda _value: False)(value):
            continue
        clean_value = _clean_text(value, 1024)
        if clean_value:
            result.append((safe_name, clean_value, requested))
    return result


def _clean_log_description(description: Any, fields: list[tuple[str, str, bool | None]]) -> str:
    text = _clean_text(description, 3900)
    if not text:
        return ""
    names = {name.casefold() for name, _value, _inline in fields}
    if not names.intersection(_IDENTITY_FIELDS):
        return text

    lines = text.splitlines()
    if (
        len(lines) >= 2
        and lines[0].strip().startswith("**")
        and lines[0].strip().endswith("**")
        and re.fullmatch(r"ID\s*:\s*`\d{5,22}`", lines[1].strip(), flags=re.IGNORECASE)
    ):
        lines = lines[2:]
        while lines and not lines[0].strip():
            lines.pop(0)
        return "\n".join(lines).strip()
    return text


def _log_colour(title: str) -> int:
    text = sx.clean_ui_text(title, 150, "").casefold()
    if any(token in text for token in (
        "débanni", "debanni", "timeout retiré", "timeout retire", "arrivé", "arrive",
        "créé", "cree", "ajouté", "ajoute", "restauré", "restaure",
        "déverrouillé", "deverrouille",
    )):
        return COLOR_SUCCESS
    if any(token in text for token in (
        "supprim", "banni", "bannissement", "expuls", "erreur", "échec", "echec",
        "refus", "bloqué", "bloque",
    )):
        return COLOR_DANGER
    if any(token in text for token in (
        "modifi", "renomm", "mise à jour", "mise a jour", "changé", "change",
    )):
        return COLOR_MODIFICATION
    if any(token in text for token in (
        "avert", "timeout appliqué", "timeout applique", "retiré", "retire", "parti",
        "départ", "depart", "désactiv", "desactiv",
    )):
        return COLOR_WARNING
    if any(token in text for token in (
        "message", "vocal", "connexion", "déconnexion", "deconnexion", "test",
        "information", "statut",
    )):
        return COLOR_INFO
    return COLOR_SYSTEM


def _log_embed(
    title: str,
    *,
    fields: Iterable[tuple[str, Any, bool | None] | tuple[str, Any]] = (),
    description: str = "",
    event_time: datetime | None = None,
    banner: bool = True,
) -> discord.Embed:
    del banner
    prepared = _coerce_fields(fields)
    body = _clean_log_description(description, prepared)
    metadata: list[str] = []
    details: list[tuple[str, str]] = []

    for name, value, requested in prepared:
        key = name.casefold()
        if key in _BEFORE_FIELDS or key in _AFTER_FIELDS:
            details.append((name, value))
            continue
        if requested is True:
            metadata.append(f"**{name} :** {_one_line(value)}")
        else:
            details.append((name, value))

    description_parts: list[str] = []
    if metadata:
        description_parts.append("\n\n".join(metadata))
    if body:
        description_parts.append(body)

    event_dt = event_time or datetime.now(timezone.utc)
    embed = discord.Embed(
        title=sx.clean_ui_text(title, 120, "Journal SentriX"),
        description="\n\n".join(description_parts) or None,
        colour=discord.Colour(_log_colour(title)),
    )
    embed.set_footer(text=f"SentriX • {sx.format_datetime_fr(event_dt)}")

    for name, value in details[:25]:
        embed.add_field(name=name, value=sx.clip(value, 1024), inline=False)
    return embed


def _normalize_log(source: discord.Embed, *, event_time: datetime | None = None) -> discord.Embed:
    fields = [(field.name, field.value, bool(field.inline)) for field in source.fields]
    panel = _log_embed(
        str(source.title or "Journal SentriX"),
        fields=fields,
        description=str(source.description or ""),
        event_time=event_time or getattr(source, "timestamp", None),
    )

    thumbnail = str(getattr(getattr(source, "thumbnail", None), "url", "") or "")
    if thumbnail:
        panel.set_thumbnail(url=thumbnail)

    image_url = str(getattr(getattr(source, "image", None), "url", "") or "")
    if image_url and not any(token in image_url.casefold() for token in (
        "sentrix-log-header", "sentrix-ping-header", "sentrix-information",
    )):
        panel.set_image(url=image_url)

    author_name = str(getattr(getattr(source, "author", None), "name", "") or "")
    author_icon = str(getattr(getattr(source, "author", None), "icon_url", "") or "")
    if author_name and not author_name.casefold().startswith(("sentrix", "odboug")):
        panel.set_author(
            name=sx.clean_ui_text(author_name, 256, "Utilisateur"),
            icon_url=author_icon or None,
        )
    return panel


def _latency_state(latency_ms: int) -> tuple[str, int]:
    if latency_ms <= 80:
        return "Excellente", COLOR_SUCCESS
    if latency_ms <= 140:
        return "Très bonne", COLOR_INFO
    if latency_ms <= 220:
        return "Correcte", COLOR_WARNING
    return "Dégradée", COLOR_DANGER


def _ping_embed(bot: commands.Bot) -> discord.Embed:
    latency_ms = max(0, round(float(getattr(bot, "latency", 0.0)) * 1000))
    quality, colour = _latency_state(latency_ms)
    guilds = list(getattr(bot, "guilds", ()) or ())
    members = sum(int(getattr(guild, "member_count", 0) or 0) for guild in guilds)
    shards = int(getattr(bot, "shard_count", None) or 1)
    is_closed = getattr(bot, "is_closed", None)
    active = not bool(is_closed()) if callable(is_closed) else True
    return _base(
        "Ping",
        (
            f"## Latence : **{latency_ms} ms**\n"
            f"**Qualité :** {quality}\n\n"
            f"**Connexion :** {'Active' if active else 'Hors ligne'}   •   "
            f"**État :** {'Opérationnel' if active else 'Indisponible'}\n"
            f"**Serveurs :** {len(guilds):,}   •   **Membres :** {members:,}   •   **Shards :** {shards}"
        ),
        footer="SentriX • Mesure en temps réel",
        colour=colour,
        kind="brand",
    )


def _clean_embed(embed: discord.Embed | None) -> discord.Embed | None:
    if not isinstance(embed, discord.Embed):
        return embed
    embed.description = _command_text(embed.description, 4096)
    for index, field in enumerate(list(embed.fields)):
        value = _clean_text(field.value, 1024) or "—"
        embed.set_field_at(index, name=field.name, value=value, inline=bool(field.inline))
    return embed


def _premium_style_embed(embed: discord.Embed, *args, **kwargs) -> discord.Embed:
    styled = _ORIGINAL_PREMIUM_STYLE_EMBED(embed, *args, **kwargs)
    return _clean_embed(styled)


def _style_existing(embed: discord.Embed | None, *args, **kwargs) -> discord.Embed | None:
    styled = _ORIGINAL_SX_STYLE_EXISTING(embed, *args, **kwargs)
    return _clean_embed(styled)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # Les vieux renderers peuvent encore générer une barre trop longue ; toutes les
    # commandes sont ensuite normalisées vers PANEL_BAR par cette dernière couche.
    runtime.BAR = PANEL_BAR
    runtime.CHANGE_BAR = ""
    sx.BAR = PANEL_BAR

    runtime._base = _base
    runtime._log_embed = _log_embed
    runtime._normalize_log = _normalize_log
    runtime._ping_embed = _ping_embed

    sx._base = _base
    sx.log_embed = _log_embed
    sx.normalize_log = _normalize_log
    sx.style_existing = _style_existing
    design_system.create_embed = _design_create_embed
    premium_style.style_embed = _premium_style_embed

    _INSTALLED = True


install()
