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
    WatchEvent("messages", "Messages envoyés", "Messages", "💬", "Chaque message qu'il écrit, avec le salon et le texte", ("intent:message_content",)),
    WatchEvent("deleted", "Messages supprimés", "Messages", "🗑️", "Ses messages effacés, avec leur ancien contenu", ("intent:message_content",)),
    WatchEvent("edited", "Messages modifiés", "Messages", "✏️", "Chaque modification, avant → après", ("intent:message_content",)),
    WatchEvent("threads", "Fils créés", "Messages", "🧵", "Les fils de discussion qu'il ouvre"),
    WatchEvent("reactions", "Réactions ajoutées", "Messages", "😀", "Chaque emoji qu'il pose sur un message", ("intent:reactions",)),
    WatchEvent("reactions_removed", "Réactions retirées", "Messages", "↩️", "Chaque emoji qu'il enlève", ("intent:reactions",)),
    WatchEvent("voice", "Vocal : arrivées et départs", "Vocal et profil", "🔊", "Quand il rejoint, quitte ou change de vocal", ("intent:voice_states",)),
    WatchEvent("voice_state", "Vocal : micro, casque, caméra", "Vocal et profil", "🎙️", "Micro ou casque coupé, caméra, partage d'écran", ("intent:voice_states",)),
    WatchEvent("presence", "Présence", "Vocal et profil", "🟢", "En ligne, absent, ne pas déranger, hors ligne", ("intent:presences",)),
    WatchEvent("profile", "Pseudo et avatar du serveur", "Vocal et profil", "🪪", "Son pseudo ou son avatar sur ce serveur", ("intent:members",)),
    WatchEvent("username", "Nom et avatar Discord", "Vocal et profil", "👤", "Son nom d'utilisateur ou son avatar global", ("intent:members",)),
    WatchEvent("roles", "Rôles reçus ou retirés", "Vocal et profil", "🎭", "Chaque rôle qu'on lui donne ou lui retire", ("intent:members",)),
    WatchEvent("timeout", "Exclusions temporaires reçues", "Sanctions et staff", "⏳", "Quand il est mis en timeout ou en sort", ("intent:members",)),
    WatchEvent("bans", "Bannissement ou débannissement", "Sanctions et staff", "🔨", "S'il est banni ou débanni, et par qui", ("intent:moderation", "perm:view_audit_log")),
    WatchEvent("join_leave", "Arrivées et départs du serveur", "Sanctions et staff", "🚪", "S'il quitte ou revient (contournement de ban)", ("intent:members",)),
    WatchEvent("invites", "Invitations créées", "Sanctions et staff", "🔗", "Les liens d'invitation qu'il crée", ("intent:invites", "perm:manage_guild")),
    WatchEvent("mod_actions", "Sanctions qu'il donne", "Sanctions et staff", "🛡️", "Ses bans, expulsions, timeouts, déplacements vocaux", ("intent:moderation", "perm:view_audit_log")),
    WatchEvent("channels", "Salons créés, modifiés, supprimés", "Sanctions et staff", "📁", "Ce qu'il fait sur les salons et les fils", ("intent:moderation", "perm:view_audit_log")),
    WatchEvent("permissions", "Permissions de salon modifiées", "Sanctions et staff", "🔐", "Les dérogations qu'il ajoute, change ou retire", ("intent:moderation", "perm:view_audit_log")),
    WatchEvent("role_admin", "Gestion des rôles", "Sanctions et staff", "🏷️", "Rôles qu'il crée, modifie, donne aux autres", ("intent:moderation", "perm:view_audit_log")),
    WatchEvent("message_admin", "Messages des autres supprimés", "Sanctions et staff", "📌", "Messages d'autres qu'il supprime ou épingle", ("intent:moderation", "perm:view_audit_log")),
)

# Trois menus courts plutôt qu'un seul de 21 cases (retour de Jayden, 26/10).
GROUPS: tuple[tuple[str, str], ...] = (
    ("Messages", "💬 Messages et réactions"),
    ("Vocal et profil", "🎙️ Vocal, profil et rôles"),
    ("Sanctions et staff", "🛡️ Sanctions, serveur et actions du staff"),
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
