"""Coordination unique des réponses IA passives SentriX.

Le problème historique venait de plusieurs listeners ``on_message`` indépendants : le
primaire, un fallback API, la récupération Discord et les conversations V5. Chacun avait
son propre set de déduplication et pouvait donc prendre une simple lenteur pour une panne.

Ce module fournit une seule machine d'état par ``message.id`` :

- ``claimed``  : un propriétaire traite actuellement le message ;
- ``released`` : implicite (entrée supprimée), le propriétaire a échoué et un secours peut
                 reprendre ;
- ``terminal`` : une réponse/commande a abouti, aucun autre listener ne doit répondre.

``claim()`` est volontairement synchrone : sur une boucle asyncio mono-thread, aucun
``await`` ne peut couper l'opération entre la lecture et l'écriture du registre. Les
secours utilisent ``wait_and_claim()`` : ils attendent la fin ou la libération du
propriétaire au lieu de conclure qu'il est mort après 1 seconde.

Une seconde couche PostgreSQL applique la même propriété entre replicas/processus Railway
lorsque le stockage durable est disponible. Le repli local reste fail-open si PostgreSQL
est indisponible, afin de ne pas rendre SentriX muet pendant une panne d'infrastructure.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("bot.ai-reply-claim")

CLAIM_TTL = 180.0
TERMINAL_TTL = 300.0
PRIMARY_GRACE = 0.20
_PROCESS_TOKEN = uuid.uuid4().hex


@dataclass
class _Entry:
    owner: str
    state: str
    updated_at: float
    event: asyncio.Event = field(default_factory=asyncio.Event)


_ENTRIES: dict[int, _Entry] = {}
_TABLE_READY_POOLS: set[int] = set()

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS sentrix_ai_reply_claims_v2 (
    instance_key TEXT NOT NULL,
    message_id BIGINT NOT NULL,
    state TEXT NOT NULL,
    owner_name TEXT NOT NULL,
    owner_token TEXT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (instance_key, message_id)
)
"""


def message_id(value: Any) -> int | None:
    try:
        raw = getattr(value, "id", value)
        return int(raw)
    except (TypeError, ValueError, AttributeError):
        return None


def _purge(now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    stale: list[int] = []
    for mid, entry in _ENTRIES.items():
        ttl = TERMINAL_TTL if entry.state == "terminal" else CLAIM_TTL
        if now - entry.updated_at >= ttl:
            stale.append(mid)
    for mid in stale[:4000]:
        entry = _ENTRIES.pop(mid, None)
        if entry is not None:
            entry.event.set()

    # Garde mémoire en cas d'activité extrême ou de clock anomalies.
    if len(_ENTRIES) > 10000:
        ordered = sorted(_ENTRIES.items(), key=lambda item: item[1].updated_at)
        for mid, entry in ordered[: len(_ENTRIES) - 8000]:
            _ENTRIES.pop(mid, None)
            entry.event.set()


def claim(value: Any, owner: str) -> bool:
    """Prend atomiquement le message dans CE processus, sans aucun ``await``."""
    mid = message_id(value)
    if mid is None:
        return True

    now = time.monotonic()
    _purge(now)
    entry = _ENTRIES.get(mid)
    if entry is None:
        _ENTRIES[mid] = _Entry(owner=str(owner), state="claimed", updated_at=now)
        return True
    if entry.state == "terminal":
        return False
    if entry.owner == str(owner):
        # Idempotence pour un même chemin qui réentre dans sa propre couche.
        entry.updated_at = now
        return True
    return False


def complete(value: Any, owner: str) -> bool:
    """Passe le claim en état terminal et réveille tous les secours."""
    mid = message_id(value)
    if mid is None:
        return True
    entry = _ENTRIES.get(mid)
    if entry is None or entry.owner != str(owner):
        return False
    entry.state = "terminal"
    entry.updated_at = time.monotonic()
    entry.event.set()
    return True


def release(value: Any, owner: str) -> bool:
    """Rend le claim après échec/annulation afin qu'un secours puisse reprendre."""
    mid = message_id(value)
    if mid is None:
        return True
    entry = _ENTRIES.get(mid)
    if entry is None or entry.owner != str(owner) or entry.state == "terminal":
        return False
    _ENTRIES.pop(mid, None)
    entry.event.set()
    return True


def state(value: Any) -> str | None:
    mid = message_id(value)
    if mid is None:
        return None
    _purge()
    entry = _ENTRIES.get(mid)
    return entry.state if entry is not None else None


async def wait_and_claim(
    value: Any,
    owner: str,
    *,
    primary_grace: float = PRIMARY_GRACE,
) -> bool:
    """Attend le propriétaire courant ; ne reprend qu'après libération/expiration.

    ``primary_grace`` n'est PAS un timeout de panne. Il sert uniquement à laisser le
    listener primaire, qui revendique sans ``await``, démarrer avant un listener de
    secours si l'ordonnanceur a réveillé le secours en premier.
    """
    mid = message_id(value)
    if mid is None:
        return True

    grace_left = max(0.0, float(primary_grace))
    while True:
        _purge()
        entry = _ENTRIES.get(mid)
        if entry is None:
            if grace_left > 0:
                delay = grace_left
                grace_left = 0.0
                await asyncio.sleep(delay)
                continue
            return claim(mid, owner)
        if entry.state == "terminal":
            return False
        if entry.owner == str(owner):
            return True

        event = entry.event
        remaining = max(0.05, CLAIM_TTL - (time.monotonic() - entry.updated_at))
        try:
            await asyncio.wait_for(event.wait(), timeout=remaining)
        except asyncio.TimeoutError:
            # La prochaine boucle purgera uniquement un claim réellement expiré.
            pass
        grace_left = 0.0


def _pool(bot: Any):
    durable = getattr(bot, "sentrix_durable_store", None)
    return getattr(durable, "pool", None), str(
        getattr(durable, "instance_key", None) or "sentrix"
    )[:120]


def _owner_token(owner: str) -> str:
    service = (os.getenv("RAILWAY_SERVICE_ID") or "local")[:80]
    replica = (os.getenv("RAILWAY_REPLICA_ID") or os.getenv("RAILWAY_DEPLOYMENT_ID") or "one")[:80]
    return f"{service}:{replica}:{_PROCESS_TOKEN}:{owner}"[:400]


async def _ensure_table(pool: Any) -> None:
    key = id(pool)
    if key in _TABLE_READY_POOLS:
        return
    await pool.execute(_CREATE_TABLE)
    _TABLE_READY_POOLS.add(key)


async def acquire_distributed(
    bot: Any,
    value: Any,
    owner: str,
    *,
    wait: bool,
) -> tuple[bool, str]:
    """Claim inter-processus PostgreSQL avec reprise seulement après release/TTL."""
    mid = message_id(value)
    if mid is None:
        return True, "no-message-id"

    pool, instance = _pool(bot)
    if pool is None:
        return True, "local-only"

    token = _owner_token(str(owner))
    try:
        await _ensure_table(pool)
        while True:
            now = int(time.time())
            row = await pool.fetchrow(
                "INSERT INTO sentrix_ai_reply_claims_v2 "
                "(instance_key,message_id,state,owner_name,owner_token,updated_at) "
                "VALUES($1,$2,'claimed',$3,$4,$5) "
                "ON CONFLICT (instance_key,message_id) DO NOTHING "
                "RETURNING owner_token",
                instance,
                mid,
                str(owner)[:120],
                token,
                now,
            )
            if row is not None:
                return True, "postgres"

            current = await pool.fetchrow(
                "SELECT state,owner_token,updated_at FROM sentrix_ai_reply_claims_v2 "
                "WHERE instance_key=$1 AND message_id=$2",
                instance,
                mid,
            )
            if current is None:
                continue
            if str(current["state"]) == "terminal":
                return False, "postgres-terminal"
            if str(current["owner_token"]) == token:
                return True, "postgres-idempotent"

            cutoff = now - int(CLAIM_TTL)
            if int(current["updated_at"] or 0) <= cutoff:
                takeover = await pool.fetchrow(
                    "UPDATE sentrix_ai_reply_claims_v2 SET state='claimed',owner_name=$3,"
                    "owner_token=$4,updated_at=$5 WHERE instance_key=$1 AND message_id=$2 "
                    "AND state='claimed' AND updated_at <= $6 RETURNING owner_token",
                    instance,
                    mid,
                    str(owner)[:120],
                    token,
                    now,
                    cutoff,
                )
                if takeover is not None:
                    return True, "postgres-stale-takeover"

            if not wait:
                return False, "postgres-busy"
            await asyncio.sleep(0.15)
    except Exception:
        logger.exception("Claim IA PostgreSQL indisponible ; repli local uniquement.")
        return True, "local-fallback"


async def complete_distributed(bot: Any, value: Any, owner: str) -> None:
    mid = message_id(value)
    if mid is None:
        return
    pool, instance = _pool(bot)
    if pool is None:
        return
    token = _owner_token(str(owner))
    try:
        now = int(time.time())
        await _ensure_table(pool)
        await pool.execute(
            "UPDATE sentrix_ai_reply_claims_v2 SET state='terminal',updated_at=$4 "
            "WHERE instance_key=$1 AND message_id=$2 AND owner_token=$3 AND state='claimed'",
            instance,
            mid,
            token,
            now,
        )
        if mid % 41 == 0:
            await pool.execute(
                "DELETE FROM sentrix_ai_reply_claims_v2 WHERE state='terminal' AND updated_at < $1",
                now - int(TERMINAL_TTL),
            )
    except Exception:
        logger.debug("Finalisation distribuée du claim IA impossible.", exc_info=True)


async def release_distributed(bot: Any, value: Any, owner: str) -> None:
    mid = message_id(value)
    if mid is None:
        return
    pool, instance = _pool(bot)
    if pool is None:
        return
    token = _owner_token(str(owner))
    try:
        await _ensure_table(pool)
        await pool.execute(
            "DELETE FROM sentrix_ai_reply_claims_v2 WHERE instance_key=$1 AND message_id=$2 "
            "AND owner_token=$3 AND state='claimed'",
            instance,
            mid,
            token,
        )
    except Exception:
        logger.debug("Libération distribuée du claim IA impossible.", exc_info=True)


def reset_for_tests() -> None:
    for entry in _ENTRIES.values():
        entry.event.set()
    _ENTRIES.clear()
    _TABLE_READY_POOLS.clear()


__all__ = [
    "CLAIM_TTL",
    "TERMINAL_TTL",
    "PRIMARY_GRACE",
    "claim",
    "complete",
    "release",
    "state",
    "wait_and_claim",
    "acquire_distributed",
    "complete_distributed",
    "release_distributed",
    "message_id",
    "reset_for_tests",
]
