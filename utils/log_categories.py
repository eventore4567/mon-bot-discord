"""Registre canonique des événements de logs SentriX.

Le type d'événement explicite détermine la catégorie, l'emoji et la bannière.
Les anciens appelants qui n'envoient encore qu'une catégorie sont conservés via un
repli lexical, uniquement pour compatibilité.
"""
from __future__ import annotations

import re

LOG_REGISTRY: dict[str, tuple[str, str, str]] = {
    # --- MODÉRATION ---
    "member_ban":       ("moderation", "🔨", "error"),
    "member_unban":     ("moderation", "🔓", "success"),
    "member_kick":      ("moderation", "👢", "error"),
    "member_timeout":   ("moderation", "⏱️", "warning"),
    "member_untimeout": ("moderation", "✅", "success"),
    "member_warn":      ("moderation", "⚠️", "warning"),

    # --- MESSAGES ---
    "message_delete":   ("messages", "🗑️", "error"),
    "message_edit":     ("messages", "✏️", "warning"),
    "message_bulk":     ("messages", "🧹", "error"),

    # --- MEMBRES ---
    "member_join":      ("members", "📥", "success"),
    "member_leave":     ("members", "📤", "error"),
    "member_update":    ("members", "👤", "info"),
    "member_roles":     ("members", "🎭", "info"),

    # --- SALONS ---
    "channel_create":   ("channels", "📗", "success"),
    "channel_delete":   ("channels", "📕", "error"),
    "channel_update":   ("channels", "📘", "info"),

    # --- RÔLES ---
    "role_create":      ("roles", "➕", "success"),
    "role_delete":      ("roles", "➖", "error"),
    "role_update":      ("roles", "🛡️", "warning"),

    # --- VOCAL ---
    "voice_join":       ("voice", "🔊", "success"),
    "voice_leave":      ("voice", "🔇", "error"),
    "voice_move":       ("voice", "↔️", "info"),
    "voice_update":     ("voice", "🎙️", "info"),

    # --- SERVEUR ---
    "guild_update":     ("server", "⚙️", "info"),
    "emoji_update":     ("server", "😀", "info"),
    "invite_create":    ("server", "🔗", "success"),
    "invite_delete":    ("server", "🔗", "error"),

    # --- TICKETS ---
    "ticket_open":      ("tickets", "📬", "success"),
    "ticket_close":     ("tickets", "🔒", "special"),
    "ticket_claim":     ("tickets", "🙋", "info"),

    # --- AUTOMOD / PROTECTION ---
    "automod_link":     ("protection", "🔗", "error"),
    "automod_spam":     ("protection", "🚫", "error"),
    "automod_word":     ("protection", "🛑", "error"),
    "antiraid":         ("protection", "🛡️", "error"),
}

CATEGORIES: dict[str, str] = {
    "moderation": "Modération",
    "messages":   "Messages",
    "members":    "Membres",
    "channels":   "Salons",
    "roles":      "Rôles",
    "voice":      "Vocal",
    "server":     "Serveur",
    "tickets":    "Tickets",
    "protection": "Protection",
}

CATEGORY_ORDER = tuple(CATEGORIES)

# Anciennes clés de configuration. Historiquement ``server`` désignait les salons.
LEGACY_CATEGORY_KEYS: dict[str, str] = {
    "messages": "messages",
    "members": "members",
    "roles": "roles",
    "server": "channels",
    "channels": "channels",
    "voice": "voice",
    "moderation": "moderation",
    "tickets": "tickets",
    "automod": "protection",
    "protection": "protection",
}

_CATEGORY_DEFAULTS: dict[str, tuple[str, str]] = {
    "moderation": ("🛡️", "info"),
    "messages": ("💬", "info"),
    "members": ("👤", "info"),
    "channels": ("#️⃣", "info"),
    "roles": ("🛡️", "info"),
    "voice": ("🎙️", "info"),
    "server": ("⚙️", "info"),
    "tickets": ("🎫", "special"),
    "protection": ("🛡️", "warning"),
}


def _norm(value: object) -> str:
    return str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")


def category_for(log_type: str) -> str:
    """Catégorie d'un événement, avec priorité aux anciennes clés pour les migrations.

    ``server`` était historiquement le groupe des logs de salons. Les nouvelles lectures
    de configuration passent par :func:`resolve`, qui sait distinguer la nouvelle
    catégorie Serveur. Garder ici le sens historique évite de déplacer les anciens salons
    configurés vers la mauvaise catégorie pendant la migration SQLite.
    """
    key = _norm(log_type)
    if key in LOG_REGISTRY:
        return LOG_REGISTRY[key][0]
    if key in LEGACY_CATEGORY_KEYS:
        return LEGACY_CATEGORY_KEYS[key]
    if key in CATEGORIES:
        return key
    return "server"


def _contains(text: str, *words: str) -> bool:
    return any(word in text for word in words)


def canonical_event_type(log_type: str, title: str = "", description: str = "") -> str:
    """Convertit les anciennes catégories en événement explicite quand le texte le permet."""
    key = _norm(log_type)
    if key in LOG_REGISTRY:
        return key

    text = f" {key} {title} {description} ".casefold()

    # Compatibilité critique : les anciens listeners utilisent ``server`` pour les
    # créations/suppressions/modifications de salons. On les reconnaît par leur texte
    # métier avant d'interpréter ``server`` comme la nouvelle catégorie Serveur.
    if key == "server" and _contains(text, "salon", "channel"):
        if _contains(text, "supprim", "delete"):
            return "channel_delete"
        if _contains(text, "cré", "cree", "create"):
            return "channel_create"
        return "channel_update"

    category = "server" if key == "server" else category_for(key)

    # Ordre important : unban/untimeout avant ban/timeout.
    if category == "moderation":
        if _contains(text, "unban", "débann", "debann", "déban", "deban"):
            return "member_unban"
        if _contains(text, "untimeout", "unmute", "démute", "demute"):
            return "member_untimeout"
        if _contains(text, "kick", "expuls"):
            return "member_kick"
        if _contains(text, "timeout", "mute", "muet"):
            return "member_timeout"
        if _contains(text, "warn", "avert"):
            return "member_warn"
        if _contains(text, "ban", "bann"):
            return "member_ban"

    if category == "messages":
        if _contains(text, "bulk", "purge", "clear", "messages supprimés", "messages supprimes"):
            return "message_bulk"
        if _contains(text, "modifi", "edit"):
            return "message_edit"
        if _contains(text, "supprim", "delete"):
            return "message_delete"

    if category == "members":
        if _contains(text, "rôle", "role"):
            return "member_roles"
        if _contains(text, "arriv", "rejoint", "join", "bienvenue"):
            return "member_join"
        if _contains(text, "parti", "départ", "depart", "quitt", "leave"):
            return "member_leave"
        return "member_update"

    if category == "channels":
        if _contains(text, "supprim", "delete"):
            return "channel_delete"
        if _contains(text, "cré", "cree", "create"):
            return "channel_create"
        return "channel_update"

    if category == "roles":
        if _contains(text, "supprim", "delete"):
            return "role_delete"
        if _contains(text, "cré", "cree", "create"):
            return "role_create"
        return "role_update"

    if category == "voice":
        if _contains(text, "déplac", "deplac", "move", "changement de salon"):
            return "voice_move"
        if _contains(text, "déconn", "deconn", "quitt", "leave"):
            return "voice_leave"
        if _contains(text, "connex", "rejoint", "join"):
            return "voice_join"
        return "voice_update"

    if category == "tickets":
        if _contains(text, "ferm", "close", "transcript"):
            return "ticket_close"
        if _contains(text, "claim", "pris en charge"):
            return "ticket_claim"
        return "ticket_open"

    if category == "protection":
        if _contains(text, "raid"):
            return "antiraid"
        if _contains(text, "spam"):
            return "automod_spam"
        if _contains(text, "lien", "link", "url"):
            return "automod_link"
        return "automod_word"

    if category == "server":
        if _contains(text, "invitation", "invite"):
            return "invite_delete" if _contains(text, "supprim", "delete", "révoqu", "revoqu") else "invite_create"
        if _contains(text, "emoji", "émoji"):
            return "emoji_update"
        return "guild_update"

    return key or "guild_update"


def _fallback_kind(text: str) -> str:
    text = text.casefold()
    if _contains(text, "unban", "débann", "debann", "unmute", "untimeout", "créé", "cree", "rejoint", "arriv", "success"):
        return "success"
    if _contains(text, "ticket ferm", "ticket close", "transcript"):
        return "special"
    if _contains(text, "warn", "avert", "timeout", "mute", "modifi", "update", "permission"):
        return "warning"
    if _contains(text, "supprim", "delete", "ban", "kick", "expuls", "quitt", "leave", "raid", "spam", "erreur", "error"):
        return "error"
    return "info"


def resolve(log_type: str, title: str = "", description: str = "") -> tuple[str, str, str]:
    """Retourne ``(catégorie, emoji, kind de bannière)``."""
    key = _norm(log_type)

    # Une clé de catégorie utilisée sans contexte vient du nouvel écran de configuration.
    # Elle doit garder son sens moderne, notamment ``server`` = Serveur.
    if key in CATEGORIES and not title and not description:
        emoji, kind = _CATEGORY_DEFAULTS.get(key, ("📋", "info"))
        return key, emoji, kind

    event_type = canonical_event_type(log_type, title, description)
    explicit = LOG_REGISTRY.get(event_type)
    if explicit is not None:
        return explicit

    category = "server" if key == "server" else category_for(log_type)
    emoji, default_kind = _CATEGORY_DEFAULTS.get(category, ("📋", "info"))
    kind = _fallback_kind(f"{log_type} {title} {description}") or default_kind
    return category, emoji, kind


__all__ = [
    "CATEGORIES",
    "CATEGORY_ORDER",
    "LEGACY_CATEGORY_KEYS",
    "LOG_REGISTRY",
    "canonical_event_type",
    "category_for",
    "resolve",
]
