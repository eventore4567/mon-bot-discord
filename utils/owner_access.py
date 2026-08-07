"""Accès au propriétaire principal de SentriX.

L'identifiant Discord brut n'est pas stocké dans le dépôt. On compare uniquement une
empreinte SHA-256 afin que les nouvelles fonctions propriétaire soient réservées à un
seul compte précis.
"""
from __future__ import annotations

import hashlib
import hmac

_PRIMARY_OWNER_DIGEST = "6f651462f7da5f989d794641b9a186b2c42c08745fe8ffff27e1c3a8f33f1bab"


def is_bot_owner_id(user_id: int | str | None) -> bool:
    try:
        value = str(int(user_id))
    except (TypeError, ValueError):
        return False
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, _PRIMARY_OWNER_DIGEST)
