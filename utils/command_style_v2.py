"""Style de commandes SentriX V2.

Cette couche reprend le langage visuel du nouveau bot : cartes compactes, vraie couleur
principale violette, titres courts, états success/warning/error lisibles et composants
cohérents. Elle ne touche à aucune logique métier et s'applique aux transports déjà
centralisés par ``plain_response_policy``.

Le dépôt historique contient plusieurs anciennes couches de présentation. Plutôt que
réécrire les centaines de commandes, ce module remplace uniquement les fonctions de
rendu consultées au dernier moment. Les commandes, permissions, callbacks, vues
persistantes, pièces jointes et données restent donc inchangés.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from typing import Any

import discord

from utils import microcopy, premium_style


_INSTALLED = False

# Palette proche de celle du nouveau bot, avec quelques accents de catégorie pour garder
# les panneaux complexes faciles à reconnaître au premier coup d'œil.
COLORS: dict[str, int] = {
    "brand": 0x8B5CF6,
    "info": 0x3B82F6,
    "success": 0x22C55E,
    "warning": 0xF59E0B,
    "danger": 0xEF4444,
    "neutral": 0x6B7280,
    "moderation": 0xEF4444,
    "security": 0x8B5CF6,
    "tickets": 0x3B82F6,
    "economy": 0xF59E0B,
    "levels": 0x22C55E,
    "games": 0x06B6D4,
    "music": 0xEC4899,
    "events": 0xF97316,
    "invites": 0x14B8A6,
    "ai": 0x8B5CF6,
    "configuration": 0x8B5CF6,
    "logs": 0x64748B,
    "utility": 0x8B5CF6,
    "profile": 0x8B5CF6,
    "shop": 0xF59E0B,
    "leaderboard": 0x6366F1,
    "premium": 0xF59E0B,
}

_GENERIC_TITLES = {
    "information",
    "action terminée",
    "action terminee",
    "action impossible",
    "vérification nécessaire",
    "verification necessaire",
    "erreur",
    "succès",
    "succes",
    "avertissement",
    "attention",
}

_SENTRIX_PREFIX = re.compile(r"^(?:SENTRIX|ODBOUG)\s*(?:/|•|—|-)\s*", re.I)
_SPACE_RE = re.compile(r"[ \t]{2,}")
_MANY_BLANKS_RE = re.compile(r"\n{3,}")


def _brand_name() -> str:
    return str(premium_style.CATEGORY_NAMES.get("brand", "SentriX") or "SentriX")


def _footer_text() -> str:
    return f"{_brand_name()} • rapide, propre, sécurisé"


def _normal_text(value: Any, *, limit: int) -> str:
    text = str(value or "").strip()
    text = _SPACE_RE.sub(" ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = _MANY_BLANKS_RE.sub("\n\n", text)
    text = microcopy.polish_text(text)
    return premium_style.clip(text, limit)


def _display_title(original: Any, category: str) -> str:
    raw = str(original or "").strip()
    raw = _SENTRIX_PREFIX.sub("", raw).strip()
    cleaned = premium_style.clean_title(raw, fallback="") if raw else ""
    if not cleaned or cleaned.casefold() in _GENERIC_TITLES:
        cleaned = premium_style.CATEGORY_NAMES.get(category, "Information")
    cleaned = premium_style.display_label(cleaned, fallback="Information")
    # Le même petit repère que sur le nouveau bot : discret, constant, jamais une rangée
    # d'emojis qui prend toute la largeur du téléphone.
    return premium_style.clip(f"✦ {cleaned}", premium_style.VISUAL_LIMITS["title"])


def _field_name(value: Any) -> str:
    text = _normal_text(value, limit=256) or "Information"
    if text.isupper() and len(text) > 3:
        text = text[:1].upper() + text[1:].lower()
    return text


def _useful_footer(embed: discord.Embed) -> str | None:
    current = str(getattr(getattr(embed, "footer", None), "text", "") or "").strip()
    if not current:
        return None
    low = current.casefold()
    if low.startswith(("sentrix", "odboug")):
        return None
    # Les numéros de page, compteurs et informations métier restent utiles.
    return _normal_text(current, limit=1500)


def style_embed(
    embed: discord.Embed,
    *,
    command: Any = None,
    guild: discord.Guild | None = None,
    requester: Any = None,
    category: str | None = None,
    kind: str | None = None,
    bot_user: discord.ClientUser | discord.User | None = None,
    log_type: str | None = None,
) -> discord.Embed:
    """Applique la carte V2 sans déplacer le vrai titre dans la description."""
    if not isinstance(embed, discord.Embed):
        return embed

    resolved_category = premium_style.infer_category(
        command=command,
        embed=embed,
        hint=category,
    )
    resolved_kind = kind or premium_style.infer_kind(embed)

    embed.title = _display_title(getattr(embed, "title", None), resolved_category)
    if embed.description is not None:
        embed.description = _normal_text(embed.description, limit=4096) or None

    state_colour = COLORS.get(resolved_kind)
    category_colour = premium_style.COLORS.get(
        resolved_category,
        COLORS.get(resolved_category, COLORS["brand"]),
    )
    if resolved_kind in {"success", "warning", "danger"} and state_colour:
        embed.colour = discord.Colour(state_colour)
    else:
        embed.colour = discord.Colour(category_colour or COLORS["brand"])

    # Comme le nouveau bot : chaque carte garde une heure précise. C'est pratique pour
    # les modérations, les tickets et les panneaux qui restent longtemps dans un salon.
    if embed.timestamp is None:
        embed.timestamp = datetime.now(timezone.utc)

    # Ne remplace jamais l'auteur métier d'un profil/citation. Sinon, une petite identité
    # SentriX donne un rendu propre et constant.
    author_name = getattr(getattr(embed, "author", None), "name", None)
    if not author_name and bot_user is not None:
        icon = getattr(getattr(bot_user, "display_avatar", None), "url", None)
        if icon:
            embed.set_author(name=_brand_name(), icon_url=str(icon))
        else:
            embed.set_author(name=_brand_name())

    useful_footer = _useful_footer(embed)
    footer = _footer_text()
    if useful_footer:
        footer = premium_style.clip(f"{useful_footer} • {_brand_name()}", 2048)
    embed.set_footer(text=footer)

    # Les miniatures et images déjà choisies par une commande sont conservées. Les champs
    # sont seulement nettoyés et alignés ; aucune donnée n'est inventée ou supprimée.
    for index, field in enumerate(list(embed.fields)[:25]):
        embed.set_field_at(
            index,
            name=_field_name(field.name),
            value=_normal_text(field.value, limit=1024) or "—",
            inline=bool(field.inline),
        )

    return embed


def style_view(view: discord.ui.View | None) -> discord.ui.View | None:
    """Boutons proches du nouveau bot : violet principal, vert validation, rouge danger."""
    if view is None:
        return None

    for item in list(getattr(view, "children", []) or []):
        if isinstance(item, discord.ui.Select):
            if item.placeholder:
                item.placeholder = _normal_text(item.placeholder, limit=150) or "Choisir une option…"
            for option in list(getattr(item, "options", []) or []):
                option.label = _normal_text(option.label, limit=100) or "Option"
                if option.description:
                    option.description = _normal_text(option.description, limit=100) or None
            continue

        if not isinstance(item, discord.ui.Button):
            continue
        if item.label:
            item.label = _normal_text(item.label, limit=80) or "Action"
        if item.style is discord.ButtonStyle.link:
            continue

        haystack = f"{item.label or ''} {item.custom_id or ''}".casefold()
        if any(word in haystack for word in (
            "supprimer", "delete", "fermer", "close", "annuler", "cancel",
            "ban", "wipe", "reset", "retirer", "remove", "stop",
        )):
            item.style = discord.ButtonStyle.danger
        elif any(word in haystack for word in (
            "enregistrer", "save", "confirmer", "confirm", "valider", "verify",
            "claim", "rouvrir", "reopen", "ajouter", "add",
        )):
            item.style = discord.ButtonStyle.success
        elif any(word in haystack for word in (
            "ouvrir", "open", "continuer", "next", "suivant", "actualiser",
            "refresh", "configurer", "setup", "créer", "create", "envoyer", "send",
            "activer", "enable",
        )):
            item.style = discord.ButtonStyle.primary
        elif item.style not in {discord.ButtonStyle.success, discord.ButtonStyle.danger}:
            item.style = discord.ButtonStyle.secondary
    return view


def _gentle_clean_text(value: Any, *, fallback: str = "") -> str:
    """Remplace l'ancienne politique 'zéro emoji' par un nettoyage non destructif."""
    if value is None:
        return fallback
    return _normal_text(value, limit=4096) or fallback


def _gentle_clean_embed(embed: discord.Embed | None) -> discord.Embed | None:
    if embed is None:
        return None
    cleaned = embed.copy()
    if cleaned.title is not None:
        cleaned.title = _gentle_clean_text(cleaned.title, fallback="SentriX")[:256]
    if cleaned.description is not None:
        cleaned.description = _gentle_clean_text(cleaned.description)[:4096]
    for index, field in enumerate(list(cleaned.fields)):
        cleaned.set_field_at(
            index,
            name=_gentle_clean_text(field.name, fallback="Information")[:256],
            value=_gentle_clean_text(field.value, fallback="—")[:1024],
            inline=bool(field.inline),
        )
    footer = getattr(cleaned.footer, "text", None)
    footer_icon = getattr(cleaned.footer, "icon_url", None)
    if footer is not None or footer_icon:
        kwargs: dict[str, Any] = {"text": _gentle_clean_text(footer, fallback=_footer_text())[:2048]}
        if footer_icon:
            kwargs["icon_url"] = str(footer_icon)
        cleaned.set_footer(**kwargs)
    return cleaned


def _gentle_clean_view(view):
    if view is None:
        return None
    # On garde volontairement les emojis choisis dans les boutons/options : un seul petit
    # pictogramme fonctionnel améliore la lecture, contrairement aux anciennes décorations.
    return style_view(view)


def _patch_help_raw_edits(bot) -> None:
    """Style aussi les pages +help qui utilisent volontairement Message.edit brut.

    L'ancien help contourne les wrappers globaux pour éviter d'autres runtimes historiques.
    On garde ce comportement, mais on applique V2 juste avant l'édition afin que l'accueil,
    les catégories, la recherche et les pages suivantes aient exactement la même carte.
    """
    module = sys.modules.get("cogs.help_clean_style")
    if module is None or getattr(module, "_sentrix_command_style_v2_patched", False):
        return

    original_edit = getattr(module, "_edit_help_message", None)
    if original_edit is None:
        return

    async def styled_edit(interaction, *, embed, view):
        style_embed(
            embed,
            guild=getattr(interaction, "guild", None),
            requester=getattr(interaction, "user", None),
            bot_user=getattr(getattr(interaction, "client", None), "user", None),
        )
        style_view(view)
        return await original_edit(interaction, embed=embed, view=view)

    module._edit_help_message = styled_edit
    module._sentrix_command_style_v2_patched = True
    if bot is not None:
        setattr(bot, "_sentrix_help_style_v2", True)


def install(bot=None) -> None:
    """Branche le thème V2 sur les moteurs historiques, de façon idempotente."""
    global _INSTALLED

    premium_style.COLORS.update(COLORS)
    premium_style.style_embed = style_embed
    premium_style.style_view = style_view

    # L'ancien finaliseur sans emoji est toujours appelé par l'architecture historique.
    # Ses fonctions de transport consultent ces helpers au moment de chaque réponse : les
    # remplacer ici suffit à garder les emojis utiles sans empiler un nouveau transport.
    try:
        from cogs import command_no_emoji_runtime as no_emoji

        no_emoji.clean_text = _gentle_clean_text
        no_emoji.clean_embed = _gentle_clean_embed
        no_emoji.clean_view = _gentle_clean_view
    except Exception:
        pass

    if bot is not None:
        _patch_help_raw_edits(bot)
        setattr(bot, "_sentrix_command_style_v2", True)
    _INSTALLED = True
