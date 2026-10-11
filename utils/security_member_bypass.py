"""Exemption des filtres de messages pour l'équipe ayant de vrais pouvoirs d'administration.

Deux configurations Discord sont admises :
- permission native Administrateur ;
- rôle de direction avec TOUS les pouvoirs sensibles de gestion, même sans bit
  Administrateur. Une seule permission comme Gérer le serveur ne suffit jamais.

Ne pas réutiliser ce prédicat pour l'anti-nuke, l'anti-raid, les journaux d'audit
ou les protections des permissions : un compte staff compromis reste dangereux.
"""

from __future__ import annotations

from typing import Any

# Cette conjonction est volontairement stricte : un modérateur ordinaire qui
# peut bannir ou gérer les messages ne devient pas immunisé par inadvertance.
_FULL_STAFF_PERMISSIONS = (
    "manage_guild",
    "manage_channels",
    "manage_roles",
    "manage_messages",
    "kick_members",
    "ban_members",
)


def can_bypass_message_filters(member: Any) -> bool:
    """Vrai pour les administrateurs et les rôles réellement « all perms »."""
    permissions = getattr(member, "guild_permissions", None)
    if permissions is None:
        return False
    if getattr(permissions, "administrator", False) is True:
        return True
    return all(getattr(permissions, name, False) is True for name in _FULL_STAFF_PERMISSIONS)


__all__ = ["can_bypass_message_filters"]
