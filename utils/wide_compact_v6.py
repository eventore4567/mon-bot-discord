"""SentriX V6 — renderer global large et bas.

Cette couche ne change aucune logique métier. Elle ajuste uniquement le rendu final :
largeur constante, hauteur réduite, champs courts regroupés horizontalement, aucune
bannière de marque et conservation des vraies images métier (avatar, résultat image...).
"""
from __future__ import annotations

import re
from typing import Any, Iterable

import discord

from . import embeds as sx


LONG_BAR = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
_BANNER_URL = str(getattr(sx, "SENTRIX_BANNER_URL", "") or "")
_INSTALLED = False


def _one_line(value: Any, limit: int = 150) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " · ")
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return sx.clip(text, limit)


def _can_compact(value: Any, requested: bool | None) -> bool:
    if requested is False:
        return False
    raw = str(value or "").strip()
    if not raw:
        return False
    # Deux petites lignes (ex. mention + ID) deviennent une seule ligne compacte.
    if raw.count("\n") > 1:
        return False
    return len(_one_line(raw, 180)) <= 180


def _compact_lines(items: list[tuple[str, str]]) -> str:
    if not items:
        return ""
    lines: list[str] = []
    current: list[str] = []
    current_len = 0
    for name, value in items:
        part = f"**{name}**  {value}"
        projected = current_len + len(part) + (5 if current else 0)
        if current and (len(current) >= 3 or projected > 135):
            lines.append("   •   ".join(current))
            current = []
            current_len = 0
        current.append(part)
        current_len += len(part) + (5 if len(current) > 1 else 0)
    if current:
        lines.append("   •   ".join(current))
    return "\n".join(lines)


def _append_compact(embed: discord.Embed, items: list[tuple[str, str]]) -> None:
    block = _compact_lines(items)
    if not block:
        return
    description = str(embed.description or "").strip()
    if not description:
        description = LONG_BAR
    elif not description.startswith(LONG_BAR):
        description = f"{LONG_BAR}\n{description}"
    combined = f"{description}\n{block}"
    embed.description = sx.clip(combined, 4096)


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
    safe_title = sx.clean_ui_text(title, 90, "Information")
    resolved_kind = kind or sx._kind_from_text(safe_title, description)
    body = sx.clean_multiline_ui_text(description, 3960) if clean_description else sx.clip(description, 3960)
    panel_description = f"{LONG_BAR}\n{body}" if body else LONG_BAR
    embed = discord.Embed(
        title=safe_title,
        description=panel_description,
        colour=discord.Colour(sx._colour(resolved_kind, colour)),
        timestamp=sx.datetime.now(sx.timezone.utc) if timestamp else None,
    )
    if thumbnail:
        embed.set_thumbnail(url=str(thumbnail))
    return sx._footer(embed, footer)


def add_fields(
    embed: discord.Embed,
    fields: Iterable[tuple[str, Any, bool | None] | tuple[str, Any]],
) -> discord.Embed:
    compact: list[tuple[str, str]] = []
    normal: list[tuple[str, str, bool]] = []

    for item in fields:
        if len(item) == 2:
            name, value = item
            requested = None
        else:
            name, value, requested = item
        if value is None or not str(value).strip():
            continue
        safe_name = sx.clean_ui_text(name, 256, "Information")
        raw_value = sx.clip(value, 1024)
        if _can_compact(raw_value, requested) and len(compact) < 9:
            compact.append((safe_name, _one_line(raw_value, 180)))
        else:
            inline = sx._field_inline(safe_name, raw_value, requested)
            normal.append((safe_name, raw_value, inline))

    _append_compact(embed, compact)
    for name, value, inline in normal:
        embed.add_field(name=name, value=value, inline=inline)
    return embed


def _compact_existing_fields(embed: discord.Embed) -> None:
    compact: list[tuple[str, str]] = []
    normal: list[tuple[str, str, bool]] = []
    for field in list(embed.fields):
        name = sx.clean_ui_text(field.name, 256, "Information")
        value = str(field.value or "—")[:1024]
        if bool(field.inline) and _can_compact(value, True) and len(compact) < 9:
            compact.append((name, _one_line(value, 180)))
        else:
            normal.append((name, value, bool(field.inline)))

    if compact:
        embed.clear_fields()
        _append_compact(embed, compact)
        for name, value, inline in normal:
            embed.add_field(name=name, value=value, inline=inline)


def _avatar_from_description(embed: discord.Embed, bot: Any) -> str | None:
    if bot is None:
        return None
    sample = f"{embed.description or ''} " + " ".join(str(f.value or "") for f in embed.fields)
    match = re.search(r"<@!?(\d{15,22})>", sample)
    if not match:
        return None
    user_id = int(match.group(1))
    target = None
    getter = getattr(bot, "get_user", None)
    if callable(getter):
        target = getter(user_id)
    if target is None:
        for guild in list(getattr(bot, "guilds", ()) or ()):
            member = guild.get_member(user_id)
            if member is not None:
                target = member
                break
    asset = getattr(target, "display_avatar", None) if target is not None else None
    if asset is None:
        return None
    try:
        asset = asset.replace(size=1024)
    except Exception:
        pass
    return str(getattr(asset, "url", "") or "") or None


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
    connection = "Active" if active else "Hors ligne"
    state = "Opérationnel" if active else "Indisponible"

    embed.title = "Ping"
    embed.description = (
        f"{LONG_BAR}\n"
        f"**Latence**  {latency_ms} ms   •   **Qualité**  {quality}   `{quality_bar}`\n"
        f"**Connexion**  {connection}   •   **État**  {state}   •   "
        f"**Serveurs**  {server_count:,}   •   **Membres**  {member_count:,}   •   **Shards**  {shard_count}"
    )
    embed.clear_fields()
    try:
        embed.remove_image()
    except Exception:
        pass
    embed.colour = discord.Colour(sx.COLOR_INFO)
    embed.set_footer(text="SentriX • Mesure en temps réel")
    return embed


def style_existing(
    embed: discord.Embed | None,
    *,
    root: str = "",
    bot: Any = None,
) -> discord.Embed | None:
    if not isinstance(embed, discord.Embed):
        return embed

    root_key = str(root or "").casefold()
    embed.title = sx.clean_ui_text(embed.title, 256, "Information")

    description = str(embed.description or "").strip()
    # Convertit aussi l'ancienne barre courte vers la nouvelle barre large.
    old_bar = str(getattr(sx, "BAR", "") or "")
    for prefix in (old_bar, LONG_BAR):
        if prefix and description.startswith(prefix):
            description = description[len(prefix):].lstrip("\n")
            break
    embed.description = f"{LONG_BAR}\n{sx.clip(description, 3970)}" if description else LONG_BAR

    # Une ancienne bannière SentriX ne doit plus survivre dans une commande.
    image_url = str(getattr(getattr(embed, "image", None), "url", "") or "")
    if image_url and _BANNER_URL and image_url == _BANNER_URL:
        try:
            embed.remove_image()
        except Exception:
            pass

    if root_key == "ping":
        return enrich_ping(embed, bot)

    _compact_existing_fields(embed)

    # +avatar garde sa vraie image. Si l'ancien code n'a rien placé, on récupère
    # l'utilisateur depuis la mention déjà présente dans la réponse.
    if root_key == "avatar":
        image_url = str(getattr(getattr(embed, "image", None), "url", "") or "")
        if not image_url:
            fallback_avatar = _avatar_from_description(embed, bot)
            if fallback_avatar:
                embed.set_image(url=fallback_avatar)

    kind = sx._kind_from_text(embed.title, embed.description)
    current_colour = int(getattr(getattr(embed, "colour", None), "value", 0) or 0)
    if kind != "brand":
        embed.colour = discord.Colour(sx._colour(kind))
    elif not current_colour:
        embed.colour = discord.Colour(sx.COLOR_BRAND_UI)

    author_name = str(getattr(getattr(embed, "author", None), "name", "") or "")
    if author_name.casefold().startswith(("sentrix", "odboug")):
        embed.remove_author()

    footer = getattr(embed.footer, "text", None)
    if footer:
        embed.set_footer(text=sx.clean_ui_text(footer, 2048, sx.SENTRIX_FOOTER))
    else:
        embed.set_footer(text=sx.SENTRIX_FOOTER)
    return embed


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    sx.BAR = LONG_BAR
    sx._base = _base
    sx.add_fields = add_fields
    sx.enrich_ping = enrich_ping
    sx.style_existing = style_existing
    _INSTALLED = True


install()
