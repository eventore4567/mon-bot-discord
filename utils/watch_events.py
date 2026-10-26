"""Catalogue des événements que `/staff watch` sait réellement surveiller.

Une seule source : le menu « Événements à suivre », les écouteurs de
`cogs/staff_suite.py` et les tests lisent cette liste. Chaque événement dit
ce dont il a besoin côté Discord (intent ou permission du bot) ; un besoin
non satisfait est affiché, jamais caché, et rien n'est activé d'office.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WatchEvent:
    key: str
    label: str
    group: str
    emoji: str
    description: str
    # « intent:<nom> » (Intents de discord.py) ou « perm:<nom> » (permission
    # de serveur du bot) ; None = aucun besoin particulier.
    requires: tuple[str, ...] = ()


EVENTS: tuple[WatchEvent, ...] = (
    WatchEvent("messages", "Messages envoyés", "Messages", "💬", "Chaque message et son contenu", ("intent:message_content",)),
    WatchEvent("deleted", "Messages supprimés", "Messages", "🗑️", "Ses messages effacés", ("intent:message_content",)),
    WatchEvent("edited", "Messages modifiés", "Messages", "✏️", "Avant / après chaque modification", ("intent:message_content",)),
    WatchEvent("threads", "Fils créés", "Messages", "🧵", "Fils ouverts par le membre"),
    WatchEvent("reactions", "Réactions ajoutées", "Réactions", "😀", "Chaque réaction posée", ("intent:reactions",)),
    WatchEvent("reactions_removed", "Réactions retirées", "Réactions", "↩️", "Chaque réaction enlevée", ("intent:reactions",)),
    WatchEvent("voice", "Vocal : arrivées / départs", "Vocal", "🔊", "Connexions et changements de salon", ("intent:voice_states",)),
    WatchEvent("voice_state", "Vocal : micro, casque, caméra", "Vocal", "🎙️", "Micro, casque, caméra, partage d'écran", ("intent:voice_states",)),
    WatchEvent("presence", "Présence", "Profil", "🟢", "En ligne, absent, hors ligne", ("intent:presences",)),
    WatchEvent("profile", "Pseudo / avatar du serveur", "Profil", "🪪", "Pseudo et avatar sur ce serveur", ("intent:members",)),
    WatchEvent("username", "Nom / avatar Discord", "Profil", "👤", "Nom d'utilisateur et avatar global", ("intent:members",)),
    WatchEvent("roles", "Rôles reçus / retirés", "Rôles", "🎭", "Chaque rôle ajouté ou enlevé", ("intent:members",)),
    WatchEvent("timeout", "Exclusions temporaires reçues", "Sanctions", "⏳", "Timeout posé ou levé sur lui", ("intent:members",)),
    WatchEvent("bans", "Bannissement / débannissement", "Sanctions", "🔨", "S'il est banni ou débanni", ("intent:moderation", "perm:view_audit_log")),
    WatchEvent("join_leave", "Arrivées / départs du serveur", "Serveur", "🚪", "Quand il rejoint ou quitte", ("intent:members",)),
    WatchEvent("invites", "Invitations créées", "Serveur", "🔗", "Liens d'invitation qu'il crée", ("intent:invites", "perm:manage_guild")),
    WatchEvent("mod_actions", "Sanctions qu'il donne", "Ses actions", "🛡️", "Bans, expulsions, timeouts, déplacements vocaux", ("intent:moderation", "perm:view_audit_log")),
    WatchEvent("channels", "Salons créés / modifiés / supprimés", "Ses actions", "📁", "Ses actions sur les salons et fils", ("intent:moderation", "perm:view_audit_log")),
    WatchEvent("permissions", "Permissions de salon modifiées", "Ses actions", "🔐", "Dérogations ajoutées, changées, retirées", ("intent:moderation", "perm:view_audit_log")),
    WatchEvent("role_admin", "Gestion des rôles", "Ses actions", "🏷️", "Rôles créés, modifiés, donnés à d'autres", ("intent:moderation", "perm:view_audit_log")),
    WatchEvent("message_admin", "Messages d'autres supprimés / épinglés", "Ses actions", "📌", "Suppressions et épinglages de modération", ("intent:moderation", "perm:view_audit_log")),
)

BY_KEY = {event.key: event for event in EVENTS}
KEYS = tuple(event.key for event in EVENTS)

_REQUIREMENT_LABELS = {
    "intent:message_content": "intent Contenu des messages",
    "intent:reactions": "intent Réactions",
    "intent:voice_states": "intent États vocaux",
    "intent:presences": "intent Présence",
    "intent:members": "intent Membres",
    "intent:moderation": "intent Modération",
    "intent:invites": "intent Invitations",
    "perm:manage_guild": "permission « Gérer le serveur »",
    "perm:view_audit_log": "permission « Voir les logs du serveur »",
}


def requirement_label(requirement: str) -> str:
    return _REQUIREMENT_LABELS.get(requirement, requirement)


def missing_requirements(event: WatchEvent, bot, guild) -> list[str]:
    """Besoins Discord non satisfaits pour cet événement, sur ce serveur."""
    missing = []
    intents = getattr(bot, "intents", None)
    me = getattr(guild, "me", None)
    perms = getattr(me, "guild_permissions", None)
    for requirement in event.requires:
        kind, _sep, name = requirement.partition(":")
        if kind == "intent" and intents is not None and not getattr(intents, name, False):
            missing.append(requirement)
        elif kind == "perm" and perms is not None and not (
            getattr(perms, name, False) or getattr(perms, "administrator", False)
        ):
            missing.append(requirement)
    return missing


def sanitize(keys) -> list[str]:
    """Clés connues seulement, dans l'ordre du catalogue."""
    wanted = {str(key) for key in keys or ()}
    return [key for key in KEYS if key in wanted]
