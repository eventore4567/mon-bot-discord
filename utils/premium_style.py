"""Identité visuelle globale premium de SentriX.

Ce module ne contient aucune logique métier. Il harmonise uniquement les messages,
embeds et composants Discord afin que tous les cogs partagent la même présentation.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import discord


COLORS: dict[str, int] = {
    "brand": 0x6C5CE7,
    "info": 0x5865F2,
    "success": 0x2FBF71,
    "warning": 0xF0B232,
    "danger": 0xED4245,
    "neutral": 0x4B5563,
    "moderation": 0xE05A67,
    "security": 0x9B6DDE,
    "tickets": 0x4C9AFF,
    "economy": 0xE8B84A,
    "levels": 0x45C98A,
    "games": 0x33B5C7,
    "music": 0xD968A6,
    "events": 0xF08A5D,
    "invites": 0x35B7A0,
    "ai": 0x8E6CE8,
    "configuration": 0x6C5CE7,
    "logs": 0x667085,
    "utility": 0x5865F2,
}

CATEGORY_NAMES: dict[str, str] = {
    "moderation": "Modération",
    "security": "Sécurité",
    "tickets": "Tickets",
    "economy": "Économie",
    "levels": "Niveaux",
    "games": "Mini-jeux",
    "music": "Musique",
    "events": "Événements",
    "invites": "Invitations",
    "ai": "Intelligence artificielle",
    "configuration": "Configuration",
    "logs": "Journal",
    "utility": "Utilitaires",
    "brand": "SentriX",
}

SYSTEM_COLOURS = {
    0x57F287, 0x23A559, 0x2ECC71,
    0xED4245, 0xF23F43, 0xE74C3C,
    0xFEE75C, 0xF0B232, 0xF39C12,
    0x5865F2, 0x5847EB, 0x7C5CFC, 0x7C6CFF,
    0x3498DB, 0x1ABC9C, 0x00BCD4, 0x8E44AD,
}

LEADING_DECORATION = re.compile(
    r"^(?:[\s\u200b]*[\W_]{1,4}[\s\u200b]*)+",
    flags=re.UNICODE,
)
SPACE_RE = re.compile(r"[ \t]{2,}")


def clip(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def clean_title(value: Any, fallback: str = "Information") -> str:
    text = clip(value, 256)
    if not text:
        return fallback
    cleaned = LEADING_DECORATION.sub("", text).strip(" —–-|•·")
    cleaned = SPACE_RE.sub(" ", cleaned).strip()
    return cleaned or fallback


def infer_kind(embed: discord.Embed | None = None, content: str = "") -> str:
    text = " ".join(
        part for part in (
            getattr(embed, "title", None) if embed else None,
            getattr(embed, "description", None) if embed else None,
            content,
        ) if part
    ).casefold()
    value = getattr(getattr(embed, "colour", None), "value", 0) if embed else 0

    if value in {0xED4245, 0xF23F43, 0xE74C3C} or any(word in text for word in (
        "erreur", "impossible", "refusé", "interdit", "introuvable", "échoué",
        "manquante", "bloqué", "banni", "sanction",
    )):
        return "danger"
    if value in {0xFEE75C, 0xF0B232, 0xF39C12} or any(word in text for word in (
        "attention", "avertissement", "à vérifier", "déjà", "recharge", "cooldown",
    )):
        return "warning"
    if value in {0x57F287, 0x23A559, 0x2ECC71} or any(word in text for word in (
        "réussi", "terminé", "enregistré", "créé", "activé", "ajouté", "envoyé",
        "configuré", "effectué",
    )):
        return "success"
    return "info"


def infer_category(*, command: Any = None, embed: discord.Embed | None = None, hint: str | None = None) -> str:
    if hint in CATEGORY_NAMES:
        return str(hint)

    cog_name = ""
    command_name = ""
    if command is not None:
        cog_name = str(getattr(command, "cog_name", "") or "").casefold()
        command_name = str(getattr(command, "qualified_name", "") or "").casefold()

    title = str(getattr(embed, "title", "") or "").casefold()
    direct_categories = {
        "moderation": "moderation",
        "automod": "security",
        "security": "security",
        "tickets": "tickets",
        "economy": "economy",
        "levels": "levels",
        "minigames": "games",
        "games_setup": "games",
        "music": "music",
        "events": "events",
        "invites": "invites",
        "ai": "ai",
        "configuration": "configuration",
        "serverbuilder": "configuration",
        "server_builder": "configuration",
        "logs": "logs",
    }
    if cog_name in direct_categories:
        return direct_categories[cog_name]

    haystack = f"{cog_name} {command_name} {title}"
    rules = (
        ("moderation", ("moderation", "sanction", "warn", "mute", "kick", "ban", "quarantaine")),
        ("security", ("automod", "security", "sécurité", "antinuke", "anti-", "blacklist")),
        ("tickets", ("ticket", "support")),
        ("economy", ("economy", "économie", "balance", "banque", "shop", "argent")),
        ("levels", ("level", "niveau", "xp", "réputation", "reputation")),
        ("games", ("game", "jeu", "trivia", "slots", "blackjack", "quiz")),
        ("music", ("music", "musique", "playlist", "queue", "lecture")),
        ("events", ("event", "giveaway", "tournoi", "tournament", "événement")),
        ("invites", ("invite", "invitation")),
        ("ai", (" ai", "intelligence", "sentrix", "openai", "image")),
        ("configuration", ("configuration", "setup", "config", "rôle", "salon", "serveur")),
        ("logs", ("log", "journal", "audit")),
    )
    for category, words in rules:
        if any(word in haystack for word in words):
            return category
    return "utility"


def _footer_text(*, guild: discord.Guild | None = None, requester: Any = None) -> str:
    parts = ["SentriX"]
    if guild is not None:
        parts.append(clip(getattr(guild, "name", "Serveur"), 60))
    if requester is not None:
        display = getattr(requester, "display_name", None) or getattr(requester, "name", None)
        if display:
            parts.append(f"demandé par {clip(display, 40)}")
    return " • ".join(parts)


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
    """Harmonise un embed existant sans supprimer ses données, images ou champs."""
    if not isinstance(embed, discord.Embed):
        return embed

    category = infer_category(command=command, embed=embed, hint=category)
    kind = kind or infer_kind(embed)

    original_title = getattr(embed, "title", None)
    if original_title:
        embed.title = clean_title(original_title)
    elif embed.description:
        embed.title = {
            "success": "Action terminée",
            "warning": "Vérification nécessaire",
            "danger": "Action impossible",
            "info": CATEGORY_NAMES.get(category, "Information"),
        }.get(kind, "Information")

    if embed.description:
        embed.description = clip(embed.description, 4096)

    current_colour = getattr(getattr(embed, "colour", None), "value", 0) or 0
    state_colour = COLORS.get(kind)
    category_colour = COLORS.get(category, COLORS["brand"])
    if kind in {"success", "warning", "danger"}:
        embed.colour = discord.Colour(state_colour)
    elif not current_colour or current_colour in SYSTEM_COLOURS:
        embed.colour = discord.Colour(category_colour)

    author_label = "SentriX"
    if log_type:
        author_label = f"SentriX • Journal {CATEGORY_NAMES.get(category, category.title())}"
    elif category != "brand":
        author_label = f"SentriX • {CATEGORY_NAMES.get(category, category.title())}"

    current_author = getattr(embed, "author", None)
    current_author_name = getattr(current_author, "name", None) if current_author else None
    if not current_author_name:
        icon_url = None
        if bot_user is not None:
            avatar = getattr(bot_user, "display_avatar", None)
            icon_url = str(avatar.url) if avatar else None
        embed.set_author(name=clip(author_label, 256), icon_url=icon_url)

    if embed.timestamp is None:
        embed.timestamp = datetime.now(timezone.utc)

    current_footer = getattr(embed, "footer", None)
    footer_text = getattr(current_footer, "text", None) if current_footer else None
    footer_icon = getattr(current_footer, "icon_url", None) if current_footer else None
    if not footer_text or str(footer_text).startswith("SentriX") or "Page " in str(footer_text):
        text = _footer_text(guild=guild, requester=requester)
        if footer_text and "Page " in str(footer_text):
            footer_value = str(footer_text)
            text = footer_value if "SentriX" in footer_value else f"{clip(footer_value, 1700)} • {text}"
        if footer_icon:
            embed.set_footer(text=clip(text, 2048), icon_url=footer_icon)
        else:
            embed.set_footer(text=clip(text, 2048))

    if len(embed.fields) > 25:
        fields = list(embed.fields[:25])
        embed.clear_fields()
        for field in fields:
            embed.add_field(
                name=clip(field.name, 256) or "Détail",
                value=clip(field.value, 1024) or "—",
                inline=field.inline,
            )
    else:
        for index, field in enumerate(list(embed.fields)):
            if len(field.name) > 256 or len(field.value) > 1024:
                embed.set_field_at(
                    index,
                    name=clip(field.name, 256) or "Détail",
                    value=clip(field.value, 1024) or "—",
                    inline=field.inline,
                )
    return embed


def can_wrap_content(content: Any, kwargs: dict[str, Any]) -> bool:
    if content is None:
        return False
    text = str(content).strip()
    if not text or len(text) > 3900:
        return False
    if any(key in kwargs for key in ("file", "files", "stickers", "poll")):
        return False
    if kwargs.get("embed") is not None or kwargs.get("embeds"):
        return False
    if re.search(r"<@!?&?\d+>|@everyone|@here", text):
        return False
    if text.startswith(("http://", "https://")):
        return False
    return True


def content_embed(
    content: Any,
    *,
    command: Any = None,
    guild: discord.Guild | None = None,
    requester: Any = None,
    bot_user: Any = None,
) -> discord.Embed:
    text = clip(content, 4096)
    kind = infer_kind(content=text)
    category = infer_category(command=command)
    title = {
        "success": "Action terminée",
        "warning": "Vérification nécessaire",
        "danger": "Action impossible",
        "info": CATEGORY_NAMES.get(category, "Information"),
    }.get(kind, "Information")
    embed = discord.Embed(title=title, description=text)
    return style_embed(
        embed,
        command=command,
        guild=guild,
        requester=requester,
        category=category,
        kind=kind,
        bot_user=bot_user,
    )


def style_view(view: discord.ui.View | None) -> discord.ui.View | None:
    """Uniformise les boutons sans toucher aux custom_id ni aux callbacks persistants."""
    if view is None:
        return None
    for item in getattr(view, "children", []):
        if not isinstance(item, discord.ui.Button) or item.style is discord.ButtonStyle.link:
            continue
        label = str(item.label or "").casefold()
        custom_id = str(item.custom_id or "").casefold()
        haystack = f"{label} {custom_id}"
        if any(word in haystack for word in ("supprimer", "delete", "fermer", "close", "annuler", "cancel", "ban", "reset", "wipe")):
            item.style = discord.ButtonStyle.danger
        elif any(word in haystack for word in ("enregistrer", "save", "confirmer", "confirm", "valider", "verify", "créer", "create", "envoyer", "send")):
            item.style = discord.ButtonStyle.success
        elif any(word in haystack for word in ("accueil", "home", "ouvrir", "open", "continuer", "next", "suivant")):
            item.style = discord.ButtonStyle.primary
        else:
            item.style = discord.ButtonStyle.secondary
    return view


def style_kwargs(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    command: Any = None,
    guild: discord.Guild | None = None,
    requester: Any = None,
    bot_user: Any = None,
    allow_content_wrap: bool = False,
    category: str | None = None,
    log_type: str | None = None,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Prépare les arguments d'un send/edit en restant compatible avec discord.py."""
    new_args = list(args)
    new_kwargs = dict(kwargs)

    content = new_kwargs.get("content")
    if content is None and new_args:
        content = new_args[0]

    embed = new_kwargs.get("embed")
    if isinstance(embed, discord.Embed):
        new_kwargs["embed"] = style_embed(
            embed,
            command=command,
            guild=guild,
            requester=requester,
            category=category,
            bot_user=bot_user,
            log_type=log_type,
        )

    embed_list = new_kwargs.get("embeds")
    if embed_list:
        new_kwargs["embeds"] = [
            style_embed(
                item,
                command=command,
                guild=guild,
                requester=requester,
                category=category,
                bot_user=bot_user,
                log_type=log_type,
            ) if isinstance(item, discord.Embed) else item
            for item in embed_list
        ]

    if allow_content_wrap and can_wrap_content(content, new_kwargs):
        wrapped = content_embed(
            content,
            command=command,
            guild=guild,
            requester=requester,
            bot_user=bot_user,
        )
        new_kwargs["embed"] = wrapped
        if new_args:
            new_args[0] = None
            new_kwargs.pop("content", None)
        else:
            new_kwargs["content"] = None

    if "view" in new_kwargs:
        new_kwargs["view"] = style_view(new_kwargs.get("view"))
    return tuple(new_args), new_kwargs
