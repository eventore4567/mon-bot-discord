"""Helpers d'accès propriétaire SentriX.

La source de vérité reste la variable Railway OWNER_IDS ; aucun identifiant personnel
n'est stocké dans le dépôt.
"""
from __future__ import annotations

import config


def is_bot_owner_id(user_id: int | str | None) -> bool:
    try:
        value = int(user_id)
    except (TypeError, ValueError):
        return False
    return value in set(config.OWNER_IDS)
