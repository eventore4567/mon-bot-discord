"""Ecriture du journal d'audit.

Append-only : le role applicatif n'a ni UPDATE ni DELETE sur audit_log
(migration 0007). L'immuabilite est garantie par PostgreSQL, pas par ce module.

L'ecriture se fait sur la connexion de la transaction courante : si la mutation
metier est annulee, son entree d'audit l'est aussi. Une entree d'audit ne decrit
donc jamais un changement qui n'a pas eu lieu.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg

from libs.ids import uuid7

__all__ = ["record"]


async def record(
    conn: asyncpg.Connection[asyncpg.Record],
    *,
    org_id: UUID,
    actor_user_id: UUID | None,
    action: str,
    target_type: str,
    target_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
    source_ip: str | None = None,
) -> UUID:
    """Enregistre une entree d'audit. Retourne son identifiant."""
    entry_id = uuid7()
    await conn.execute(
        """
        INSERT INTO audit_log
            (id, org_id, actor_user_id, action, target_type, target_id, metadata, source_ip)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::inet)
        """,
        entry_id,
        org_id,
        actor_user_id,
        action,
        target_type,
        target_id,
        json.dumps(metadata or {}),
        source_ip,
    )
    return entry_id
