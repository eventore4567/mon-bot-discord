"""SentriX V3.9 — système visuel unifié et plus léger.

Cette couche reste strictement visuelle : aucune permission, aucune commande et aucune
logique métier ne sont modifiées.

Objectif V3.9 : rendre les panneaux réellement uniformes sans leur donner artificiellement
la même hauteur. L'ancien V3.4 ajoutait des champs invisibles pour remplir les grandes
cartes ; cela produisait des panneaux trop hauts et irréguliers selon le client Discord.
V3.9 remplace cette approche par un contrat simple :

- deux densités seulement : compact et panel ;
- aucun champ vide ajouté ;
- titres courts et métier, jamais un gros branding répété ;
- grands panneaux organisés en sections pleine largeur ;
- petites métriques autorisées en inline, le reste reste lisible sur toute la largeur ;
- descriptions et champs raccourcis proprement, sans casser les logs Secure Audit ;
- boutons et sélecteurs gardent la même grammaire visuelle partout.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import discord
from discord.ext import commands

from utils import premium_style

logger = logging.getLogger("bot.sentrix-v3-global-style")
_INSTALLED = False

_CANONICAL_TITLE_RE = re.compile(r"^SentriX\s*•\s*(.+)$", re.IGNORECASE)
_LEADING_DETAIL_RE = re.compile(r"^\*\*(.{1,96}?)\*\*(?:\n+|$)")
_MANY_BLANKS_RE = re.compile(r"\n{3,}")
_DECORATIVE_TITLE_RE = re.compile(r"^[\s\u200b]*(?:[^\wÀ-ÿ]{1,4}\s*)+")
_ZWSP = "\u200b"

_GENERIC_STATE_TITLES = {
    "success": "Action réussie",
    "warning": "À vérifier",
    "danger": "Action impossible",
    "info": "Information",
}

_BUTTON_EMOJIS = (
    (("configurer", "configuration", "setup", "paramètre", "settings"), "⚙️"),
    (("enregistrer", "save", "sauvegarder"), "💾"),
    (("confirmer", "confirm", "valider", "verify"), "✅"),
    (("rechercher", "search"), "🔎"),
    (("actualiser", "refresh", "recharger"), "🔄"),
    (("support", "ticket"), "🎫"),
    (("sécurité", "security"), "🛡️"),
    (("modération", "moderation"), "🔨"),
    (("dashboard", "tableau de bord"), "🌐"),
    (("inviter", "invite"), "➕"),
    (("retour", "back", "précédent", "precedent"), "⬅️"),
    (("suivant", "next"), "➡️"),
    (("fermer", "close", "annuler", "cancel"), "❌"),
    (("supprimer", "delete", "effacer"), "🗑️"),
)

_PANEL_COMMAND_HINTS = {
    "help", "setup", "profile", "profile-card", "userinfo", "botinfo",
    "ticketsetup", "ticket", "shoppanel", "shop", "inventory", "leaderboard-levels",
    "economyleaderboard", "command-stats", "server-growth", "security-check",
    "automod-status", "config-view", "rolepanel", "diagnostic", "bot-status",
    "security", "antiraid", "antinuke", "giveaway", "warnings",
}
_PANEL_CATEGORIES = {
    "configuration", "tickets", "profile", "shop", "leaderboard", "premium",
    "security", "moderation",
}

# Limites éditoriales, volontairement sous les limites Discord.
_COMPACT_DESCRIPTION_LIMIT = 460
_PANEL_DESCRIPTION_LIMIT = 1150
_COMPACT_FIELD_LIMIT = 260
_PANEL_FIELD_LIMIT = 620
_PANEL_TITLE_LIMIT = 56
_COMPACT_TITLE_LIMIT = 44


def _asset_url(bot_user: Any) -> str | None:
    avatar = getattr(getattr(bot_user, "display_avatar", None), "url", None)
    return str(avatar) if avatar else None


def _category_label(category: str) -> str:
    return str(premium_style.CATEGORY_NAMES.get(category, "SentriX"))


def _compact_description(value: Any, *, limit: int = 4096) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = _MANY_BLANKS_RE.sub("\n\n", text)
    return premium_style.clip(text, limit)


def _clean_panel_title(value: Any, *, fallback: str) -> str:
    text = premium_style.clean_title(value, fallback=fallback)
    text = _DECORATIVE_TITLE_RE.sub("", text).strip()
    return premium_style.clip(text or fallback, _PANEL_TITLE_LIMIT)


def _promote_real_title(embed: discord.Embed, *, kind: str) -> None:
    current_title = str(getattr(embed, "title", "") or "").strip()
    description = _compact_description(getattr(embed, "description", None))

    canonical = _CANONICAL_TITLE_RE.match(current_title)
    if canonical is None:
        if current_title:
            embed.title = _clean_panel_title(current_title, fallback="Information")
        embed.description = description
        return

    match = _LEADING_DETAIL_RE.match(description or "")
    if match:
        promoted = _clean_panel_title(match.group(1), fallback="Information")
        if promoted:
            embed.title = promoted
            remaining = (description or "")[match.end():].lstrip()
            embed.description = remaining or None
            return

    # Pour une carte informative, le nom métier/catégorie est beaucoup plus utile que
    # « Information ». Les états courts conservent un titre d'état explicite.
    if kind == "info":
        suffix = _clean_panel_title(canonical.group(1), fallback="Information")
        embed.title = suffix
    else:
        embed.title = _GENERIC_STATE_TITLES.get(kind, "Information")
    embed.description = description


def _set_premium_author(embed: discord.Embed, *, category: str, bot_user: Any) -> None:
    current = getattr(getattr(embed, "author", None), "name", None)
    current_text = str(current or "").strip()
    if current_text and not current_text.casefold().startswith("sentrix"):
        return

    # Le titre porte déjà le contexte métier : l'auteur reste uniquement la marque.
    icon = _asset_url(bot_user)
    if icon:
        embed.set_author(name="SentriX", icon_url=icon)
    else:
        embed.set_author(name="SentriX")


def _is_blank_field(name: Any, value: Any) -> bool:
    clean_name = str(name or "").replace(_ZWSP, "").strip()
    clean_value = str(value or "").replace(_ZWSP, "").strip()
    return not clean_name and not clean_value


def _refine_fields(embed: discord.Embed) -> None:
    """Nettoie les champs sans en créer artificiellement."""
    refined: list[tuple[str, str, bool]] = []
    for field in list(embed.fields):
        if _is_blank_field(field.name, field.value):
            continue
        name = premium_style.display_label(field.name, "Information")
        value = _compact_description(field.value) or "—"
        refined.append((
            premium_style.clip(name, 256),
            premium_style.clip(value, 1024),
            bool(field.inline),
        ))

    embed.clear_fields()
    for name, value, inline in refined:
        embed.add_field(name=name, value=value, inline=inline)


def _refine_footer(embed: discord.Embed, *, category: str, guild: discord.Guild | None) -> None:
    footer = getattr(embed, "footer", None)
    footer_text = str(getattr(footer, "text", "") or "").strip()
    footer_icon = getattr(footer, "icon_url", None)

    if footer_text and not footer_text.casefold().startswith("sentrix"):
        return

    parts: list[str] = []
    if category not in {"brand", "utility"}:
        parts.append(_category_label(category))
    if guild is not None:
        parts.append(premium_style.clip(getattr(guild, "name", "Serveur"), 38))
    text = " • ".join(parts) if parts else "SentriX"
    if footer_icon:
        embed.set_footer(text=text, icon_url=footer_icon)
    else:
        embed.set_footer(text=text)


def _command_name(command: Any) -> str:
    return str(getattr(command, "qualified_name", "") or "").casefold().strip()


def _has_media(embed: discord.Embed) -> bool:
    thumbnail = str(getattr(getattr(embed, "thumbnail", None), "url", "") or "")
    image = str(getattr(getattr(embed, "image", None), "url", "") or "")
    return bool(thumbnail or image)


def _layout_size(embed: discord.Embed, *, command: Any, category: str) -> str:
    command_name = _command_name(command)
    description = str(getattr(embed, "description", "") or "")

    if command_name in _PANEL_COMMAND_HINTS:
        return "panel"
    if any(command_name.startswith(f"{name} ") for name in _PANEL_COMMAND_HINTS):
        return "panel"
    if category in _PANEL_CATEGORIES:
        return "panel"
    if _has_media(embed):
        return "panel"
    if len(embed.fields) >= 3 or len(description) > _COMPACT_DESCRIPTION_LIMIT:
        return "panel"
    return "compact"


def _field_should_be_inline(name: str, value: str, *, original_inline: bool) -> bool:
    """Réserve les colonnes aux vraies petites métriques, pas aux paragraphes."""
    if not original_inline:
        return False
    if len(value) > 150 or value.count("\n") > 2:
        return False
    if "```" in value or len(name) > 34:
        return False
    return True


def _apply_compact_layout(embed: discord.Embed) -> None:
    if embed.title:
        embed.title = premium_style.clip(embed.title, _COMPACT_TITLE_LIMIT)
    if embed.description:
        embed.description = _compact_description(embed.description, limit=_COMPACT_DESCRIPTION_LIMIT)

    rebuilt: list[tuple[str, str, bool]] = []
    for field in list(embed.fields):
        if _is_blank_field(field.name, field.value):
            continue
        value = _compact_description(field.value, limit=_COMPACT_FIELD_LIMIT) or "—"
        rebuilt.append((premium_style.clip(field.name, 80), value, False))
    embed.clear_fields()
    for name, value, inline in rebuilt[:3]:
        embed.add_field(name=name, value=value, inline=inline)


def _apply_panel_layout(embed: discord.Embed) -> None:
    """Structure les gros panneaux sans padding ni grille artificielle."""
    if embed.title:
        embed.title = premium_style.clip(embed.title, _PANEL_TITLE_LIMIT)
    if embed.description:
        embed.description = _compact_description(embed.description, limit=_PANEL_DESCRIPTION_LIMIT)

    rebuilt: list[tuple[str, str, bool]] = []
    for field in list(embed.fields):
        if _is_blank_field(field.name, field.value):
            continue
        name = premium_style.clip(field.name, 72)
        value = _compact_description(field.value, limit=_PANEL_FIELD_LIMIT) or "—"
        inline = _field_should_be_inline(name, value, original_inline=bool(field.inline))
        rebuilt.append((name, value, inline))

    embed.clear_fields()
    for name, value, inline in rebuilt:
        embed.add_field(name=name, value=value, inline=inline)


def _apply_two_size_layout(embed: discord.Embed, *, size: str) -> None:
    # Nom conservé pour compatibilité avec les tests/couches V3.4 historiques.
    if size in {"large", "panel"}:
        _apply_panel_layout(embed)
    else:
        _apply_compact_layout(embed)


def _dedupe_title_field(embed: discord.Embed) -> None:
    """Évite « Configuration » puis un champ « Configuration » juste dessous."""
    title = premium_style.clean_title(getattr(embed, "title", ""), fallback="").casefold()
    if not title or not embed.fields:
        return
    first = embed.fields[0]
    first_name = premium_style.clean_title(first.name, fallback="").casefold()
    if first_name != title:
        return
    value = str(first.value or "").strip()
    remaining = list(embed.fields)[1:]
    body = str(getattr(embed, "description", "") or "").strip()
    if value and value != "—":
        embed.description = _compact_description(f"{body}\n\n{value}" if body else value, limit=_PANEL_DESCRIPTION_LIMIT)
    embed.clear_fields()
    for field in remaining:
        embed.add_field(name=field.name, value=field.value, inline=field.inline)


def _refine_embed(
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
    del requester
    resolved_category = premium_style.infer_category(command=command, embed=embed, hint=category)
    resolved_kind = kind or premium_style.infer_kind(embed)

    # Les logs Secure Audit ont leur propre contrat visuel et ne doivent pas être remodelés.
    is_log = bool(log_type) or resolved_category == "logs"
    if is_log:
        return embed

    _set_premium_author(embed, category=resolved_category, bot_user=bot_user)
    _promote_real_title(embed, kind=resolved_kind)
    _refine_fields(embed)

    state_colours = {
        "success": premium_style.COLORS["success"],
        "warning": premium_style.COLORS["warning"],
        "danger": premium_style.COLORS["danger"],
    }
    if resolved_kind in state_colours:
        embed.colour = discord.Colour(state_colours[resolved_kind])
    elif resolved_category in premium_style.COLORS:
        embed.colour = discord.Colour(premium_style.COLORS[resolved_category])

    size = _layout_size(embed, command=command, category=resolved_category)
    _apply_two_size_layout(embed, size=size)
    if size == "panel":
        _dedupe_title_field(embed)
    _refine_footer(embed, category=resolved_category, guild=guild)
    return embed


def _safe_button_emoji(item: discord.ui.Button) -> None:
    if item.emoji is not None or not item.label:
        return
    haystack = f"{item.label} {item.custom_id or ''}".casefold()
    for words, emoji in _BUTTON_EMOJIS:
        if any(word in haystack for word in words):
            try:
                item.emoji = emoji
            except (TypeError, ValueError):
                pass
            return


def _refine_view(view: discord.ui.View | None) -> discord.ui.View | None:
    if view is None:
        return None
    for item in list(getattr(view, "children", ()) or ()):
        if isinstance(item, discord.ui.Button):
            label = str(item.label or "").strip()
            if label:
                item.label = premium_style.clip(label, premium_style.VISUAL_LIMITS["button_label"])
            _safe_button_emoji(item)
        elif isinstance(item, discord.ui.Select):
            placeholder = str(item.placeholder or "").strip()
            item.placeholder = premium_style.clip(
                placeholder or "Choisir une option…",
                premium_style.VISUAL_LIMITS["select_label"],
            )
    return view


def install(bot: commands.Bot) -> None:
    global _INSTALLED

    if not _INSTALLED:
        original_embed = premium_style.style_embed
        original_view = premium_style.style_view

        def styled_v39(embed: discord.Embed, *args, **kwargs):
            result = original_embed(embed, *args, **kwargs)
            if not isinstance(result, discord.Embed):
                return result
            return _refine_embed(
                result,
                command=kwargs.get("command"),
                guild=kwargs.get("guild"),
                requester=kwargs.get("requester"),
                bot_user=kwargs.get("bot_user"),
                category=kwargs.get("category"),
                kind=kwargs.get("kind"),
                log_type=kwargs.get("log_type"),
            )

        def styled_view_v39(view: discord.ui.View | None):
            return _refine_view(original_view(view))

        premium_style.style_embed = styled_v39
        premium_style.style_view = styled_view_v39
        _INSTALLED = True
        logger.info("SentriX V3.9 : design uniforme compact/panel sans padding artificiel actif.")

    # Le pack d'emojis est installé après le moteur visuel afin qu'une ancienne couche ne
    # puisse pas remplacer ses composants. Les logs restent exclus des transformations.
    try:
        from .sentrix_emoji_runtime import install as install_animated_emoji_pack
        install_animated_emoji_pack(bot)
    except Exception:
        logger.exception("Impossible d'installer le pack animé SentriX.")


__all__ = ["install", "_layout_size", "_apply_two_size_layout", "_refine_embed"]
