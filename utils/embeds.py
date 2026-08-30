"""Design system Discord officiel et unique de SentriX.

Toutes les commandes utilisent des cartes larges et sobres : aucune bannière, aucun emoji
décoratif, une barre de séparation constante et une couleur lisible selon l'état.
Les journaux utilisent le même langage visuel tout en conservant les valeurs métier,
mentions, raisons et contenus de messages tels quels.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Iterable

import discord

from config import COLOR_BRAND

SENTRIX_COLOR = int(COLOR_BRAND)
SENTRIX_FOOTER = "SentriX"
SENTRIX_BANNER_URL = (
    "https://raw.githubusercontent.com/eventore4567/mon-bot-discord/"
    "main/assets/sentrix-log-header.png"
)
FOOTER_TEXT = SENTRIX_FOOTER
FOOTER_ICON: str | None = None
BAR = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

COLOR_INFO = 0x3B82F6
COLOR_SUCCESS = 0x22C55E
COLOR_WARNING = 0xF59E0B
COLOR_DANGER = 0xEF4444
COLOR_NEUTRAL = 0x64748B
COLOR_BRAND_UI = 0x7C3AED

_CUSTOM_EMOJI_RE = re.compile(r"<a?:[A-Za-z0-9_]{2,32}:\d+>")
_SPACE_RE = re.compile(r"[ \t]{2,}")
_EMPTY_LOG_VALUES = {
    "aucune", "aucun", "aucune raison", "aucune raison fournie",
    "non précisé", "non précisée", "non precise", "non precisee",
    "null", "none", "undefined", "nan",
}
_LEGACY_FILLER_FIELDS = {"historique"}


def _is_emoji_codepoint(code: int) -> bool:
    return (
        0x1F000 <= code <= 0x1FAFF
        or 0x2600 <= code <= 0x27BF
        or 0x2300 <= code <= 0x23FF
        or 0x2B00 <= code <= 0x2BFF
        or code in {0xFE0E, 0xFE0F, 0x200D, 0x20E3}
    )


def strip_emojis(value: Any) -> str:
    text = _CUSTOM_EMOJI_RE.sub("", str(value or ""))
    return "".join(char for char in text if not _is_emoji_codepoint(ord(char)))


def clean_ui_text(value: Any, limit: int = 256, fallback: str = "") -> str:
    text = strip_emojis(value)
    text = _SPACE_RE.sub(" ", text.replace("\r", " ")).strip(" \n\t-•·|:/")
    if not text:
        text = fallback
    if len(text) > limit:
        text = text[: max(1, limit - 1)].rstrip() + "…"
    return text


def clean_multiline_ui_text(value: Any, limit: int = 4096) -> str:
    text = strip_emojis(value).replace("\r", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return clip(text, limit)


def clip(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _empty_log_value(value: Any) -> bool:
    return str(value or "").strip().casefold() in _EMPTY_LOG_VALUES


def set_footer_icon(url: str) -> None:
    global FOOTER_ICON
    FOOTER_ICON = str(url or "").strip() or None


def set_footer_text(text: str) -> None:
    global FOOTER_TEXT
    FOOTER_TEXT = clean_ui_text(text, 120, SENTRIX_FOOTER) or SENTRIX_FOOTER


def set_brand_color(color: int) -> None:
    global SENTRIX_COLOR
    SENTRIX_COLOR = int(color)


def set_banner_url(url: str) -> None:
    global SENTRIX_BANNER_URL
    value = str(url or "").strip()
    if value:
        SENTRIX_BANNER_URL = value


def format_datetime_fr(value: datetime | None = None) -> str:
    dt = value or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%d/%m/%Y à %H:%M")


def _kind_from_text(title: Any, description: Any = "") -> str:
    text = f"{title or ''} {description or ''}".casefold()
    if any(word in text for word in (
        "erreur", "impossible", "introuvable", "refus", "interdit", "échoué",
        "echoue", "banni", "bannissement", "supprimé", "supprime",
    )):
        return "danger"
    if any(word in text for word in (
        "attention", "avertissement", "vérification", "verification", "cooldown",
        "recharge", "attendre", "limite",
    )):
        return "warning"
    if any(word in text for word in (
        "succès", "succes", "effectuée", "effectuee", "effectué", "effectue",
        "réussi", "reussi", "créé", "cree", "ajouté", "ajoute", "activé",
        "active", "enregistré", "enregistre", "terminé", "termine",
    )):
        return "success"
    if any(word in text for word in ("information", "statut", "ping", "profil", "aide")):
        return "info"
    return "brand"


def _colour(kind: str | None = None, fallback: int | None = None) -> int:
    if fallback is not None:
        return int(fallback)
    return {
        "info": COLOR_INFO,
        "success": COLOR_SUCCESS,
        "warning": COLOR_WARNING,
        "danger": COLOR_DANGER,
        "neutral": COLOR_NEUTRAL,
        "brand": COLOR_BRAND_UI,
    }.get(str(kind or "").casefold(), SENTRIX_COLOR)


def _panel_description(description: Any, *, clean: bool = True) -> str:
    body = clean_multiline_ui_text(description, 3970) if clean else clip(description, 3970)
    if body.startswith(BAR):
        return body
    return f"{BAR}\n{body}" if body else BAR


def _footer(embed: discord.Embed, text: str | None = None) -> discord.Embed:
    footer = clean_ui_text(text or FOOTER_TEXT, 160, SENTRIX_FOOTER) or SENTRIX_FOOTER
    if FOOTER_ICON:
        embed.set_footer(text=footer, icon_url=FOOTER_ICON)
    else:
        embed.set_footer(text=footer)
    return embed


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
    safe_title = clean_ui_text(title, 90, "Information")
    resolved_kind = kind or _kind_from_text(safe_title, description)
    embed = discord.Embed(
        title=safe_title,
        description=_panel_description(description, clean=clean_description),
        colour=discord.Colour(_colour(resolved_kind, colour)),
        timestamp=datetime.now(timezone.utc) if timestamp else None,
    )
    if thumbnail:
        embed.set_thumbnail(url=str(thumbnail))
    if banner and SENTRIX_BANNER_URL:
        embed.set_image(url=SENTRIX_BANNER_URL)
    return _footer(embed, footer)


def standard(title: str, description: str = "", *, thumbnail: str | None = None, timestamp: bool = False) -> discord.Embed:
    return _base(title, description or None, thumbnail=thumbnail, timestamp=timestamp)


def success(description: str, title: str = "Action effectuée") -> discord.Embed:
    return _base(title, description, colour=SENTRIX_COLOR)


def error(description: str, title: str = "Erreur") -> discord.Embed:
    return _base(title, description, colour=SENTRIX_COLOR)


def warning(description: str, title: str = "Vérification nécessaire") -> discord.Embed:
    return _base(title, description, colour=SENTRIX_COLOR)


def info(description: str, title: str = "Information") -> discord.Embed:
    return _base(title, description, kind="info")


def neutral(title: str, description: str = "", color: int | None = None) -> discord.Embed:
    return _base(title, description, kind="neutral", colour=color)


def brand(title: str, description: str = "") -> discord.Embed:
    return _base(title, description, kind="brand")


def category(category_name: str, title: str, description: str = "") -> discord.Embed:
    del category_name
    return brand(title, description)


def panel(title: str, description: str = "", *, category_name: str = "configuration", thumbnail: str | None = None) -> discord.Embed:
    del category_name
    return _base(title, description, thumbnail=thumbnail, kind="brand")


def help_embed(title: str = "Commandes", description: str = "") -> discord.Embed:
    return _base(title, description, colour=SENTRIX_COLOR)


def profile_embed(title: str = "Profil", description: str = "", *, thumbnail: str | None = None) -> discord.Embed:
    return _base(title, description, thumbnail=thumbnail, kind="info")


def large(title: str, description: str = "", *, thumbnail: str | None = None, timestamp: bool = False) -> discord.Embed:
    return _base(title, description, thumbnail=thumbnail, timestamp=timestamp)


def _field_inline(name: str, value: str, requested: bool | None) -> bool:
    if requested is not None:
        return bool(requested)
    normalized = clean_ui_text(name, 80).casefold()
    long_labels = {
        "raison", "motif", "message", "contenu", "avant", "après", "apres",
        "description", "permissions", "permissions ajoutées", "permissions supprimées",
        "changements", "transcript", "pièces jointes", "pieces jointes",
    }
    if normalized in long_labels:
        return False
    return len(str(value or "")) <= 150 and str(value or "").count("\n") <= 1


def add_fields(embed: discord.Embed, fields: Iterable[tuple[str, Any, bool | None] | tuple[str, Any]]) -> discord.Embed:
    for item in fields:
        if len(item) == 2:
            name, value = item
            requested = None
        else:
            name, value, requested = item
        if value is None or str(value).strip() == "":
            continue
        safe_name = clean_ui_text(name, 256, "Information")
        raw_value = clip(value, 1024)
        if not raw_value:
            continue
        embed.add_field(name=safe_name, value=raw_value, inline=_field_inline(safe_name, raw_value, requested))
    return embed


def _latency_quality(latency_ms: int) -> tuple[str, str]:
    if latency_ms <= 80:
        return "Excellente", "██████████"
    if latency_ms <= 140:
        return "Très bonne", "█████████░"
    if latency_ms <= 220:
        return "Correcte", "███████░░░"
    return "Dégradée", "████░░░░░░"


def enrich_ping(embed: discord.Embed, bot: Any) -> discord.Embed:
    if bot is None:
        return embed
    latency_ms = max(0, round(float(getattr(bot, "latency", 0.0)) * 1000))
    quality, quality_bar = _latency_quality(latency_ms)
    guilds = list(getattr(bot, "guilds", ()) or ())
    server_count = len(guilds)
    member_count = sum(int(guild.member_count or 0) for guild in guilds)
    shard_count = int(getattr(bot, "shard_count", None) or 1)
    is_closed = getattr(bot, "is_closed", None)
    active = not bool(is_closed()) if callable(is_closed) else True
    embed.title = "Ping"
    embed.description = f"{BAR}\n**Latence**  {latency_ms} ms   •   **Qualité**  {quality}   `{quality_bar}`"
    embed.clear_fields()
    embed.add_field(name="Connexion", value="Active" if active else "Hors ligne", inline=True)
    embed.add_field(name="État", value="Opérationnel" if active else "Indisponible", inline=True)
    embed.add_field(name="Serveurs", value=f"{server_count:,}", inline=True)
    embed.add_field(name="Membres", value=f"{member_count:,}", inline=True)
    embed.add_field(name="Shards", value=str(shard_count), inline=True)
    embed.colour = discord.Colour(COLOR_INFO)
    embed.set_footer(text="SentriX • Mesure en temps réel")
    return embed


def style_existing(embed: discord.Embed | None, *, root: str = "", bot: Any = None) -> discord.Embed | None:
    if not isinstance(embed, discord.Embed):
        return embed
    embed.title = clean_ui_text(embed.title, 256, "Information") if embed.title else "Information"
    description = str(embed.description or "").strip()
    if not description.startswith(BAR):
        embed.description = f"{BAR}\n{clip(description, 3970)}" if description else BAR
    for index, field in enumerate(list(embed.fields)):
        embed.set_field_at(index, name=clean_ui_text(field.name, 256, "Information"), value=str(field.value or "—")[:1024], inline=bool(field.inline))
    kind = _kind_from_text(embed.title, embed.description)
    current_colour = int(getattr(getattr(embed, "colour", None), "value", 0) or 0)
    if kind != "brand":
        embed.colour = discord.Colour(_colour(kind))
    elif not current_colour:
        embed.colour = discord.Colour(COLOR_BRAND_UI)
    author_name = str(getattr(getattr(embed, "author", None), "name", "") or "")
    if author_name.casefold().startswith(("sentrix", "odboug")):
        embed.remove_author()
    footer = getattr(embed.footer, "text", None)
    embed.set_footer(text=clean_ui_text(footer, 2048, SENTRIX_FOOTER) if footer else SENTRIX_FOOTER)
    if str(root or "").casefold() == "ping":
        enrich_ping(embed, bot)
    return embed


def _iter_view_items(view: Any):
    seen: set[int] = set()
    queue = list(getattr(view, "children", ()) or ())
    while queue:
        item = queue.pop(0)
        if id(item) in seen:
            continue
        seen.add(id(item))
        yield item
        queue.extend(list(getattr(item, "children", ()) or ()))


def clean_view(view: Any) -> Any:
    if view is None:
        return None
    for item in _iter_view_items(view):
        if isinstance(item, discord.ui.Button):
            if item.label:
                item.label = clean_ui_text(item.label, 80, "Action")
            try:
                item.emoji = None
            except Exception:
                pass
            continue
        if isinstance(item, discord.ui.Select):
            if item.placeholder:
                item.placeholder = clean_ui_text(item.placeholder, 150, "Choisir une option…")
            for option in list(getattr(item, "options", ()) or ()):
                option.label = clean_ui_text(option.label, 100, "Option")
                if option.description:
                    option.description = clean_ui_text(option.description, 100, "") or None
                try:
                    option.emoji = None
                except Exception:
                    pass
            continue
        content = getattr(item, "content", None)
        if isinstance(content, str):
            try:
                item.content = strip_emojis(content)
            except Exception:
                pass
    return view


def log_embed(title: str, *, fields: Iterable[tuple[str, Any, bool | None] | tuple[str, Any]] = (), description: str = "", event_time: datetime | None = None, banner: bool = True) -> discord.Embed:
    footer = f"SentriX • {format_datetime_fr(event_time)}"
    embed = _base(title, description or None, footer=footer, kind=_kind_from_text(title, description), clean_description=False, banner=banner)
    return add_fields(embed, fields)


def normalize_log(source: discord.Embed, *, event_time: datetime | None = None) -> discord.Embed:
    fields = []
    for field in source.fields:
        safe_name = clean_ui_text(field.name, 256, "Information")
        if safe_name.casefold() in _LEGACY_FILLER_FIELDS or _empty_log_value(field.value):
            continue
        fields.append((safe_name, str(field.value), bool(field.inline)))
    panel = log_embed(str(source.title or "Journal SentriX"), description=str(source.description or ""), fields=fields, event_time=event_time)
    thumbnail = getattr(source.thumbnail, "url", None)
    if thumbnail:
        panel.set_thumbnail(url=str(thumbnail))
    author_name = getattr(source.author, "name", None)
    author_icon = getattr(source.author, "icon_url", None)
    if author_name and not str(author_name).casefold().startswith(("sentrix", "odboug")):
        panel.set_author(name=clean_ui_text(author_name, 256, "SentriX"), icon_url=str(author_icon) if author_icon else None)
    return panel


def _who(entity: Any) -> str:
    if entity is None:
        return ""
    entity_id = getattr(entity, "id", None)
    mention = getattr(entity, "mention", None)
    if mention and entity_id:
        return f"{mention}\n`{entity_id}`"
    if entity_id:
        return f"{entity}\n`{entity_id}`"
    return str(entity)


def log_entry(title: str, color: int | None = None, *, cible=None, cible_label: str = "Cible", acteur=None, acteur_label: str = "Modérateur", raison: str | None = None, extra: dict | None = None) -> discord.Embed:
    del color
    fields: list[tuple[str, Any, bool | None]] = []
    if cible is not None:
        fields.append((cible_label, _who(cible), True))
    if acteur is not None:
        fields.append((acteur_label, _who(acteur), True))
    if extra:
        for name, value in list(extra.items())[:20]:
            if value is not None and str(value).strip() and not _empty_log_value(value):
                fields.append((name, value, None))
    if raison and not _empty_log_value(raison):
        fields.append(("Raison", raison, False))
    return log_embed(title, fields=fields)


def bar(value: float, maximum: float, length: int = 10, filled_char: str = "█", empty_char: str = "░") -> str:
    try:
        ratio = float(value) / float(maximum) if maximum else 0.0
    except (TypeError, ValueError, ZeroDivisionError):
        ratio = 0.0
    filled = max(0, min(length, round(length * max(0.0, min(1.0, ratio)))))
    return filled_char * filled + empty_char * (length - filled)


def is_official_log_embed(embed: discord.Embed | None) -> bool:
    """Détection conservée pour compatibilité, sans monkey-patch de transport."""
    if embed is None:
        return False
    footer = str(getattr(getattr(embed, "footer", None), "text", "") or "")
    return bool(re.match(r"^SentriX\s*•\s*\d{2}/\d{2}/\d{4}", footer))
