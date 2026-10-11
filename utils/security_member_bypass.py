"""Permissions de bypass des filtres de messages SentriX.

Les membres disposant de la permission Discord « Administrateur » OU « Gérer
le serveur » peuvent contourner les filtres de messages SentriX, y compris
anti-liens et anti-invitations. Cela correspond aux autres règles de salon
SentriX et évite d'exiger une combinaison arbitraire de six permissions.

Une permission partielle (Gérer les messages, Bannir, Gérer les rôles, etc.)
ou un rôle simplement nommé « Admin » ne suffit jamais.

Cette fonction ne doit pas être utilisée pour désactiver les protections
globales anti-nuke, anti-raid ni le journal d'audit.
"""

from __future__ import annotations

from typing import Any


def can_bypass_message_filters(member: Any) -> bool:
    """Exempter les véritables responsables du serveur, pas un nom de rôle."""
    permissions = getattr(member, "guild_permissions", None)
    if permissions is None:
        return False
    return (
        getattr(permissions, "administrator", False) is True
        or getattr(permissions, "manage_guild", False) is True
    )


__all__ = ["can_bypass_message_filters"]
