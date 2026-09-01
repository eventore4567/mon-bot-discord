"""Registre canonique des journaux SentriX.

Un événement possède un ``log_type`` explicite. Ce registre est l'unique endroit qui
transforme ce type en catégorie configurable, emoji et type de bannière.
"""
from __future__ import annotations

CATEGORIES: dict[str, str] = {
    "moderation": "Modération",
    "messages": "Messages",
    "members": "Membres",
    "channels": "Salons",
    "roles": "Rôles",
    "voice": "Vocal",
    "server": "Serveur",
    "tickets": "Tickets",
    "automod": "AutoMod",
    "spam": "Anti-Spam",
    "raid": "Anti-Raid",
    "resources": "Ressources",
    "files": "Fichiers",
}
CATEGORY_ORDER = tuple(CATEGORIES)
CATEGORY_META = {key: {"label": label, "emits": True} for key, label in CATEGORIES.items()}
DEFAULT_CATEGORY = "server"

LOG_REGISTRY: dict[str, tuple[str, str, str]] = {
    "member_kick": ("moderation", "👢", "error"),
    "member_ban": ("moderation", "🔨", "error"),
    "member_unban": ("moderation", "🔓", "success"),
    "member_timeout": ("moderation", "⏱️", "warning"),
    "member_untimeout": ("moderation", "✅", "success"),
    "member_warn": ("moderation", "⚠️", "warning"),
    "member_clear": ("moderation", "🧹", "warning"),
    "message_delete": ("messages", "🗑️", "error"),
    "message_edit": ("messages", "✏️", "warning"),
    "message_bulk": ("messages", "🧹", "error"),
    "member_join": ("members", "📥", "success"),
    "member_leave": ("members", "📤", "error"),
    "member_remove": ("members", "📤", "error"),
    "member_update": ("members", "👤", "info"),
    "member_roles": ("roles", "🎭", "info"),
    "role_add": ("roles", "➕", "info"),
    "role_remove": ("roles", "➖", "info"),
    "channel_create": ("channels", "📗", "success"),
    "channel_delete": ("channels", "📕", "error"),
    "channel_update": ("channels", "📘", "info"),
    "pins_update": ("channels", "📌", "info"),
    "role_create": ("roles", "➕", "success"),
    "role_delete": ("roles", "➖", "error"),
    "role_update": ("roles", "🛡️", "warning"),
    "voice_join": ("voice", "🔊", "success"),
    "voice_leave": ("voice", "🔇", "error"),
    "voice_move": ("voice", "↔️", "info"),
    "voice_state": ("voice", "🎙️", "info"),
    "voice_update": ("voice", "🎙️", "info"),
    "guild_update": ("server", "⚙️", "info"),
    "ticket_open": ("tickets", "📬", "success"),
    "ticket_close": ("tickets", "🔒", "special"),
    "ticket_claim": ("tickets", "🙋", "info"),
    "automod_link": ("automod", "🔗", "error"),
    "automod_word": ("automod", "🛑", "error"),
    "automod_mention": ("automod", "📣", "error"),
    "automod_spam": ("spam", "🚫", "error"),
    "spam_detected": ("spam", "🚫", "error"),
    "spam_purge": ("spam", "🧹", "warning"),
    "antiraid": ("raid", "🛡️", "error"),
    "raid_detected": ("raid", "🛡️", "error"),
    "raid_lockdown": ("raid", "🔒", "error"),
    "emoji_update": ("resources", "😀", "info"),
    "invite_create": ("resources", "🔗", "success"),
    "invite_delete": ("resources", "🔗", "error"),
    "sticker_update": ("resources", "🧩", "info"),
    "webhook_update": ("resources", "🔗", "warning"),
    "resource_add": ("resources", "📎", "success"),
    "resource_remove": ("resources", "📎", "error"),
    "file_delete": ("files", "📎", "error"),
    "file_upload": ("files", "📁", "info"),
    "file_blocked": ("files", "⛔", "error"),
}

LEGACY_EVENT_ALIASES: dict[str, str] = {
    "kick": "member_kick",
    "ban": "member_ban",
    "unban": "member_unban",
    "timeout": "member_timeout",
    "untimeout": "member_untimeout",
    "warn": "member_warn",
    "clear": "member_clear",
    "bulk_delete": "message_bulk",
    "member_add": "member_join",
    "member_departure": "member_leave",
}

LEGACY_CATEGORY_KEYS: dict[str, str] = {
    **{key: key for key in CATEGORIES},
    "protection": "automod",
    "system": "server",
    "dossiers": "resources",
    "log_moderation": "moderation",
    "log_messages": "messages",
    "log_members": "members",
    "log_channels": "channels",
    "log_roles": "roles",
    "log_voice": "voice",
    "log_server": "server",
    "log_channel": "server",
    "ticket_log_channel": "tickets",
    "log_tickets": "tickets",
    "log_automod": "automod",
    "log_protection": "automod",
    "log_spam": "spam",
    "log_raid": "raid",
    "log_resources": "resources",
    "log_dossiers": "resources",
    "log_files": "files",
}

# Emoji par type d'événement, indexé sur log_type. Dérivé du registre pour qu'il ne
# puisse jamais diverger de la catégorie et du style de bannière du même événement.
EVENT_EMOJI: dict[str, str] = {
    log_type: emoji for log_type, (_category, emoji, _kind) in LOG_REGISTRY.items()
}
DEFAULT_EVENT_EMOJI = "📋"

LOGS = LOG_REGISTRY


def _norm(value: object) -> str:
    return str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")


def _canonical_category(value: str) -> str:
    key = _norm(value)
    # Alias legacy AVANT CATEGORIES : même si un ancien runtime rajoute temporairement
    # ``dossiers`` au dictionnaire, il reste canoniquement ``resources``.
    if key in LEGACY_CATEGORY_KEYS:
        return LEGACY_CATEGORY_KEYS[key]
    if key in CATEGORIES:
        return key
    return DEFAULT_CATEGORY


def canonical_event_type(log_type: str, title: str = "", description: str = "") -> str:
    key = LEGACY_EVENT_ALIASES.get(_norm(log_type), _norm(log_type))
    if key in LOG_REGISTRY or key in CATEGORIES or key in LEGACY_CATEGORY_KEYS:
        return key
    sample = f"{title} {description}".casefold()
    checks = (
        ("message supprim", "message_delete"),
        ("message modifi", "message_edit"),
        ("membre arriv", "member_join"),
        ("membre parti", "member_leave"),
        ("expuls", "member_kick"),
        ("débanni", "member_unban"),
        ("banni", "member_ban"),
        ("salon créé", "channel_create"),
        ("salon supprim", "channel_delete"),
        ("salon modifi", "channel_update"),
        ("rôle créé", "role_create"),
        ("rôle supprim", "role_delete"),
        ("rôle modifi", "role_update"),
        ("invitation créée", "invite_create"),
        ("invitation supprim", "invite_delete"),
    )
    for token, event in checks:
        if token in sample:
            return event
    return key or "guild_update"


def category_for(log_type: str, title: str = "", description: str = "") -> str:
    key = canonical_event_type(log_type, title, description)
    if key in LOG_REGISTRY:
        return _canonical_category(LOG_REGISTRY[key][0])
    return _canonical_category(key)


def resolve(log_type: str, title: str = "", description: str = "") -> tuple[str, str, str]:
    key = canonical_event_type(log_type, title, description)
    if key in LOG_REGISTRY:
        category, emoji, kind = LOG_REGISTRY[key]
        return _canonical_category(category), emoji, kind
    return _canonical_category(key), "📋", "info"


def legacy_to_category(value: str) -> str | None:
    key = _norm(value)
    if not key:
        return None
    if key in LEGACY_CATEGORY_KEYS:
        return LEGACY_CATEGORY_KEYS[key]
    if key in LOG_REGISTRY:
        return _canonical_category(LOG_REGISTRY[key][0])
    if key in CATEGORIES:
        return _canonical_category(key)
    if key.startswith("log_"):
        tail = key[4:]
        if tail in LEGACY_CATEGORY_KEYS:
            return LEGACY_CATEGORY_KEYS[tail]
        if tail in LOG_REGISTRY:
            return _canonical_category(LOG_REGISTRY[tail][0])
    return None


__all__ = [
    "CATEGORIES", "CATEGORY_META", "CATEGORY_ORDER", "DEFAULT_CATEGORY",
    "DEFAULT_EVENT_EMOJI", "EVENT_EMOJI", "LEGACY_CATEGORY_KEYS", "LEGACY_EVENT_ALIASES",
    "LOG_REGISTRY", "LOGS",
    "canonical_event_type", "category_for", "legacy_to_category", "resolve",
]
