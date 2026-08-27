"""Autorité finale : une seule réponse IA passive par message Discord.

Ce module ne crée aucun cooldown. Deux messages Discord différents restent indépendants,
même s'ils arrivent au même instant.

La garantie est appliquée à deux niveaux :
- un seul ``cogs.ai.Ai.on_message`` reste enregistré sur le service SentriX principal ;
- juste avant ``Ai.send_sentrix_reply(..., reply_to=message)``, un claim atomique PostgreSQL
  par ``(instance_key, message_id)`` décide quel processus/replica a le droit de répondre.

Le verrou PostgreSQL est partagé entre tous les processus Railway. Si PostgreSQL est
indisponible, un verrou local par ``message.id`` reste actif en repli. Les commandes + et /
ne sont jamais concernées car elles n'utilisent pas ``reply_to``.
"""
from __future__ import annotations

import functools
import logging
import os
import time
from typing import Callable

from discord.ext import commands

logger = logging.getLogger("bot.passive-ai-single-reply-final")

PRIMARY_RAILWAY_SERVICE_ID = "d4fb0c3a-d62b-4817-aae1-3cfc859d32c0"
PRIMARY_RAILWAY_SERVICE_NAME = "mon-bot-discord"
_MESSAGE_TTL = 60.0
_PG_RETENTION_SECONDS = 900
_RECENT_MESSAGE_IDS: dict[int, float] = {}
_MARKER = "_sentrix_passive_ai_single_reply_final"
_SEND_MARKER = "_sentrix_passive_ai_shared_claim_final"
_TABLE_READY_POOLS: set[int] = set()

_CREATE_CLAIM_TABLE = """
CREATE TABLE IF NOT EXISTS sentrix_passive_ai_claims (
    instance_key TEXT NOT NULL,
    message_id BIGINT NOT NULL,
    claimed_at BIGINT NOT NULL,
    service_id TEXT,
    deployment_id TEXT,
    replica_id TEXT,
    PRIMARY KEY (instance_key, message_id)
)
"""


def _is_primary_service() -> bool:
    """Décide localement, sans dépendre d'un ancien monkey-patch runtime."""
    service_id = (os.getenv("RAILWAY_SERVICE_ID") or "").strip()
    if service_id:
        return service_id == PRIMARY_RAILWAY_SERVICE_ID

    service_name = (os.getenv("RAILWAY_SERVICE_NAME") or "").strip().casefold()
    if service_name:
        primary = PRIMARY_RAILWAY_SERVICE_NAME.casefold()
        return service_name == primary or service_name.endswith(" - " + primary)

    # En CI/local il n'y a pas plusieurs services Railway concurrents.
    return not bool((os.getenv("RAILWAY_PROJECT_ID") or "").strip())


def _message_id(message) -> int | None:
    try:
        return int(message.id)
    except (AttributeError, TypeError, ValueError):
        return None


def _claim_message(message) -> bool:
    """Repli local, strictement indexé par l'ID Discord source."""
    message_id = _message_id(message)
    if message_id is None:
        return True

    now = time.monotonic()
    if _RECENT_MESSAGE_IDS.get(message_id, 0.0) > now:
        return False

    _RECENT_MESSAGE_IDS[message_id] = now + _MESSAGE_TTL
    if len(_RECENT_MESSAGE_IDS) > 5000:
        stale = [mid for mid, expiry in _RECENT_MESSAGE_IDS.items() if expiry <= now]
        for mid in stale[:2000]:
            _RECENT_MESSAGE_IDS.pop(mid, None)
        if len(_RECENT_MESSAGE_IDS) > 5000:
            for mid in list(_RECENT_MESSAGE_IDS)[:1000]:
                _RECENT_MESSAGE_IDS.pop(mid, None)
    return True


async def _ensure_claim_table(pool) -> None:
    key = id(pool)
    if key in _TABLE_READY_POOLS:
        return
    await pool.execute(_CREATE_CLAIM_TABLE)
    _TABLE_READY_POOLS.add(key)


async def _claim_shared(bot: commands.Bot, message) -> tuple[bool, str]:
    """Claim atomique global ; retourne ``(autorisé, mode)``.

    PostgreSQL est prioritaire. Le fallback local ne sert que si la base durable n'est pas
    disponible. Un message différent possède une autre clé et n'est donc jamais ralenti.
    """
    message_id = _message_id(message)
    if message_id is None:
        return True, "no_message_id"

    durable = getattr(bot, "sentrix_durable_store", None)
    pool = getattr(durable, "pool", None)
    instance = str(getattr(durable, "instance_key", None) or "sentrix")[:120]

    if pool is not None:
        try:
            await _ensure_claim_table(pool)
            now = int(time.time())
            row = await pool.fetchrow(
                "INSERT INTO sentrix_passive_ai_claims "
                "(instance_key,message_id,claimed_at,service_id,deployment_id,replica_id) "
                "VALUES($1,$2,$3,$4,$5,$6) "
                "ON CONFLICT (instance_key,message_id) DO NOTHING "
                "RETURNING message_id",
                instance,
                message_id,
                now,
                (os.getenv("RAILWAY_SERVICE_ID") or "")[:120],
                (os.getenv("RAILWAY_DEPLOYMENT_ID") or "")[:120],
                (os.getenv("RAILWAY_REPLICA_ID") or "")[:120],
            )
            # Nettoyage opportuniste très léger. Il n'affecte pas le claim courant.
            if message_id % 37 == 0:
                try:
                    await pool.execute(
                        "DELETE FROM sentrix_passive_ai_claims WHERE claimed_at < $1",
                        now - _PG_RETENTION_SECONDS,
                    )
                except Exception:
                    logger.debug("Nettoyage claims IA passifs impossible.", exc_info=True)
            return row is not None, "postgres"
        except Exception:
            logger.exception(
                "Claim PostgreSQL IA passive impossible ; repli local — message=%s",
                message_id,
            )

    return _claim_message(message), "local"


def _is_ai_on_message(callback: Callable) -> bool:
    function = getattr(callback, "__func__", callback)
    module = str(getattr(function, "__module__", ""))
    name = str(getattr(function, "__name__", ""))
    owner = getattr(callback, "__self__", None)
    owner_module = str(getattr(getattr(owner, "__class__", None), "__module__", ""))
    owner_name = str(getattr(getattr(owner, "__class__", None), "__name__", ""))
    return name == "on_message" and (
        module == "cogs.ai" or (owner_module == "cogs.ai" and owner_name == "Ai")
    )


def _install_send_claim(bot: commands.Bot) -> bool:
    """Place le verrou global au dernier point commun avant toute réponse passive."""
    cog = bot.get_cog("Ai")
    if cog is None:
        return False

    cls = type(cog)
    current = cls.send_sentrix_reply
    if getattr(current, _SEND_MARKER, False):
        return True

    @functools.wraps(current)
    async def one_global_passive_reply(self, destination, author, question: str, *, reply_to=None):
        if reply_to is not None:
            if not _is_primary_service():
                logger.info(
                    "Réponse IA passive bloquée sur service secondaire — message=%s",
                    getattr(reply_to, "id", "?"),
                )
                return None

            allowed, mode = await _claim_shared(bot, reply_to)
            state = getattr(bot, "passive_ai_single_reply_state", None)
            if isinstance(state, dict):
                state["last_claim_mode"] = mode
                state["last_message_id"] = _message_id(reply_to)
                state["last_claim_allowed"] = allowed
                state["last_claim_at"] = int(time.time())

            if not allowed:
                logger.warning(
                    "Double réponse IA passive bloquée globalement — message=%s mode=%s",
                    getattr(reply_to, "id", "?"),
                    mode,
                )
                return None

        return await current(
            self,
            destination,
            author,
            question,
            reply_to=reply_to,
        )

    setattr(one_global_passive_reply, _SEND_MARKER, True)
    one_global_passive_reply._sentrix_original = current
    cls.send_sentrix_reply = one_global_passive_reply
    return True


def _reconcile_ai_listener(bot: commands.Bot) -> tuple[int, bool]:
    listeners = list((getattr(bot, "extra_events", {}) or {}).get("on_message", ()) or ())
    ai_listeners = [callback for callback in listeners if _is_ai_on_message(callback)]

    removed = 0
    for callback in ai_listeners:
        try:
            bot.remove_listener(callback, "on_message")
            removed += 1
        except (ValueError, TypeError):
            pass

    if not _is_primary_service() or not ai_listeners:
        return removed, False

    # Un seul propriétaire. Le claim n'est volontairement PAS fait ici : il est placé sur
    # send_sentrix_reply afin de couvrir aussi tout autre chemin interne qui l'appellerait.
    original = ai_listeners[0]
    bot.add_listener(original, "on_message")
    return removed, True


def install(bot: commands.Bot) -> None:
    """Installe l'autorité après le chargement complet du runtime Railway."""
    removed, installed_listener = _reconcile_ai_listener(bot)
    send_claim_installed = _install_send_claim(bot)
    primary = _is_primary_service()

    bot.passive_ai_single_reply_state = {
        "installed": True,
        "primary_service": primary,
        "ai_listeners_removed": removed,
        "active_ai_listener": installed_listener,
        "send_claim_installed": send_claim_installed,
        "postgres_available": bool(
            getattr(getattr(bot, "sentrix_durable_store", None), "pool", None)
        ),
        "service_id": (os.getenv("RAILWAY_SERVICE_ID") or "").strip(),
        "service_name": (os.getenv("RAILWAY_SERVICE_NAME") or "").strip(),
        "last_claim_mode": None,
        "last_message_id": None,
        "last_claim_allowed": None,
        "last_claim_at": None,
    }
    setattr(bot, _MARKER, True)

    if primary:
        logger.warning(
            "IA passive finale : %s listener(s) Ai réconcilié(s), claim global=%s, postgres=%s.",
            removed,
            send_claim_installed,
            bot.passive_ai_single_reply_state["postgres_available"],
        )
    else:
        logger.warning(
            "IA passive désactivée sur le service Railway secondaire : %s listener(s) retiré(s).",
            removed,
        )


__all__ = [
    "install",
    "_is_primary_service",
    "_claim_message",
    "_claim_shared",
    "_is_ai_on_message",
]
