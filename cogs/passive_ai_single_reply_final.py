"""Autorité finale : une seule réponse IA passive par message Discord.

Les anciennes couches SentriX ont ajouté plusieurs listeners ``on_message`` capables de
répondre :
- ``cogs.ai.Ai.on_message`` (primaire) ;
- ``cogs.ai_api_hotfix.fallback_on_message`` (ancien secours API) ;
- ``cogs.ai_reply_recovery.backup_on_message`` (secours Discord) ;
- ``cogs.bot_experience_v5.natural_continuation`` (DM/continuations).

Leurs anciens sets privés ne pouvaient pas se voir. Une réponse primaire un peu lente
pouvait donc être doublée après 1,0/1,25 s.

Cette couche, installée en DERNIER par ``slash_error_completion_guard``, réconcilie les
listeners réellement enregistrés et les fait tous passer par ``utils.ai_reply_claim`` :
le primaire revendique avant son premier await ; les secours attendent un release réel ;
un succès devient terminal. Le même protocole est aussi appliqué via PostgreSQL entre
processus/replicas Railway quand le stockage durable est disponible.
"""
from __future__ import annotations

import functools
import logging
import os
import re
import time
from collections import Counter
from typing import Callable

from discord.ext import commands

import config
from utils import ai_reply_claim

logger = logging.getLogger("bot.passive-ai-single-reply-final")

PRIMARY_RAILWAY_SERVICE_ID = "d4fb0c3a-d62b-4817-aae1-3cfc859d32c0"
PRIMARY_RAILWAY_SERVICE_NAME = "mon-bot-discord"
_MARKER = "_sentrix_passive_ai_single_reply_final"
_WRAPPER_MARKER = "_sentrix_ai_reply_claim_wrapper"
_NATURAL_TRIGGER = re.compile(
    r"^(?:sentrix|ssentrix|sentri|snetri|snentrix)\b",
    re.IGNORECASE,
)

_KIND_BY_MODULE = {
    "cogs.ai": "primary",
    "cogs.ai_api_hotfix": "api_fallback",
    "cogs.ai_reply_recovery": "recovery",
    "cogs.bot_experience_v5": "experience",
}


def _is_primary_service() -> bool:
    """Un seul service Railway conserve les réponses naturelles SentriX."""
    service_id = (os.getenv("RAILWAY_SERVICE_ID") or "").strip()
    if service_id:
        return service_id == PRIMARY_RAILWAY_SERVICE_ID

    service_name = (os.getenv("RAILWAY_SERVICE_NAME") or "").strip().casefold()
    if service_name:
        primary = PRIMARY_RAILWAY_SERVICE_NAME.casefold()
        return service_name == primary or service_name.endswith(" - " + primary)

    # En CI/local, il n'y a pas les deux services Railway concurrents.
    return not bool((os.getenv("RAILWAY_PROJECT_ID") or "").strip())


def _unwrap(callback: Callable) -> Callable:
    current = callback
    seen: set[int] = set()
    while getattr(current, _WRAPPER_MARKER, False):
        ident = id(current)
        if ident in seen:
            break
        seen.add(ident)
        original = getattr(current, "_sentrix_original", None)
        if original is None:
            break
        current = original
    return current


def _identity(callback: Callable) -> tuple[str | None, str, Callable]:
    original = _unwrap(callback)
    function = getattr(original, "__func__", original)
    module = str(getattr(function, "__module__", ""))
    name = str(getattr(function, "__name__", ""))
    owner = getattr(original, "__self__", None)
    owner_module = str(getattr(getattr(owner, "__class__", None), "__module__", ""))

    kind = _KIND_BY_MODULE.get(module) or _KIND_BY_MODULE.get(owner_module)
    if kind == "primary" and name != "on_message":
        kind = None
    elif kind == "api_fallback" and name != "fallback_on_message":
        kind = None
    elif kind == "recovery" and name != "backup_on_message":
        kind = None
    elif kind == "experience" and name != "natural_continuation":
        kind = None
    return kind, name, original


def _prefix(bot: commands.Bot, message) -> str:
    guild = getattr(message, "guild", None)
    if guild is not None and hasattr(bot, "prefix_cache"):
        return str(bot.prefix_cache.get(guild.id, config.DEFAULT_PREFIX))
    return str(config.DEFAULT_PREFIX)


def _explicit_trigger(bot: commands.Bot, message) -> bool:
    author = getattr(message, "author", None)
    if author is None or getattr(author, "bot", False):
        return False
    content = str(getattr(message, "content", "") or "").strip()
    if not content:
        return False
    prefix = _prefix(bot, message)
    if prefix and content.startswith(prefix):
        return False

    bot_user = getattr(bot, "user", None)
    mentioned = bool(bot_user is not None and bot_user in (getattr(message, "mentions", []) or []))
    return mentioned or _NATURAL_TRIGGER.match(content) is not None


def _should_coordinate(bot: commands.Bot, kind: str, message) -> bool:
    """Ne revendique que les messages que le listener concerné peut réellement traiter."""
    if kind == "primary":
        return getattr(message, "guild", None) is not None and _explicit_trigger(bot, message)
    if kind in {"api_fallback", "recovery"}:
        return _explicit_trigger(bot, message)
    if kind == "experience":
        # V5 ne concurrence les autres couches que dans les DM. En serveur, ses
        # continuations par réponse excluent explicitement mention/wake-word.
        if getattr(message, "guild", None) is not None:
            return False
        author = getattr(message, "author", None)
        if author is None or getattr(author, "bot", False):
            return False
        content = str(getattr(message, "content", "") or "").strip()
        if not content:
            return False
        prefix = _prefix(bot, message)
        return not bool(prefix and content.startswith(prefix))
    return False


def _runtime_state(bot: commands.Bot) -> dict:
    state = getattr(bot, "passive_ai_single_reply_state", None)
    if not isinstance(state, dict):
        state = {}
        bot.passive_ai_single_reply_state = state
    return state


def _record(bot: commands.Bot, **values) -> None:
    state = _runtime_state(bot)
    state.update(values)
    state["updated_at"] = int(time.time())


async def _run_claimed(
    bot: commands.Bot,
    original: Callable,
    message,
    *,
    kind: str,
    owner: str,
    backup: bool,
):
    if not _should_coordinate(bot, kind, message):
        return await original(message)

    mid = ai_reply_claim.message_id(message)
    if mid is None:
        return await original(message)

    if backup:
        local_allowed = await ai_reply_claim.wait_and_claim(message, owner)
    else:
        # Synchrone et AVANT tout await : le primaire réserve immédiatement l'ID.
        local_allowed = ai_reply_claim.claim(message, owner)

    if not local_allowed:
        _record(
            bot,
            last_message_id=mid,
            last_owner=owner,
            last_result="blocked_local_terminal_or_busy",
        )
        return None

    distributed_allowed, distributed_mode = await ai_reply_claim.acquire_distributed(
        bot,
        message,
        owner,
        wait=backup,
    )
    if not distributed_allowed:
        # Un autre process a soit terminé, soit (pour le primaire) possède encore le claim.
        # On libère localement afin qu'un secours de CE process puisse reprendre si le
        # propriétaire distant échoue plus tard.
        ai_reply_claim.release(message, owner)
        _record(
            bot,
            last_message_id=mid,
            last_owner=owner,
            last_claim_mode=distributed_mode,
            last_result="blocked_distributed",
        )
        return None

    _record(
        bot,
        last_message_id=mid,
        last_owner=owner,
        last_claim_mode=distributed_mode,
        last_result="running",
    )

    try:
        result = await original(message)
    except BaseException as exc:
        # Inclut asyncio.CancelledError : une annulation ne doit jamais laisser un claim
        # bloqué qui rendrait tous les secours muets.
        await ai_reply_claim.release_distributed(bot, message, owner)
        ai_reply_claim.release(message, owner)
        _record(
            bot,
            last_message_id=mid,
            last_owner=owner,
            last_result="released_after_error",
            last_error=type(exc).__name__,
        )
        raise
    else:
        await ai_reply_claim.complete_distributed(bot, message, owner)
        ai_reply_claim.complete(message, owner)
        _record(
            bot,
            last_message_id=mid,
            last_owner=owner,
            last_result="terminal",
            last_error=None,
        )
        return result


def _make_wrapper(bot: commands.Bot, original: Callable, kind: str, ordinal: int):
    owner = f"{kind}:{ordinal}"
    backup = kind in {"api_fallback", "recovery"}

    @functools.wraps(original)
    async def coordinated(message):
        return await _run_claimed(
            bot,
            original,
            message,
            kind=kind,
            owner=owner,
            backup=backup,
        )

    setattr(coordinated, _WRAPPER_MARKER, True)
    coordinated._sentrix_original = original
    coordinated._sentrix_ai_reply_kind = kind
    coordinated._sentrix_ai_reply_owner = owner
    return coordinated


def install(bot: commands.Bot) -> None:
    """Réconcilie TOUS les responders IA après chargement complet des cogs."""
    listeners = list((getattr(bot, "extra_events", {}) or {}).get("on_message", ()) or ())
    responders: list[tuple[Callable, str, Callable]] = []
    for callback in listeners:
        kind, _name, original = _identity(callback)
        if kind is not None:
            responders.append((callback, kind, original))

    counts = Counter(kind for _callback, kind, _original in responders)
    primary_service = _is_primary_service()

    # Retirer toutes les copies/wrappers historiques de ces responders. Les listeners
    # logs, automod, niveaux, etc. ne sont jamais touchés.
    removed = 0
    for callback, _kind, _original in responders:
        try:
            bot.remove_listener(callback, "on_message")
            removed += 1
        except (ValueError, TypeError):
            pass

    wrapped: list[str] = []
    hotfix_removed = 0

    if primary_service:
        # Une seule copie du listener primaire. Les doublons exacts historiques sont jetés.
        primary_seen = False
        recovery_available = counts.get("recovery", 0) > 0
        ordinals: Counter[str] = Counter()

        for _callback, kind, original in responders:
            if kind == "primary":
                if primary_seen:
                    continue
                primary_seen = True

            # ai_reply_recovery est le secours canonique : lorsqu'il existe, garder en plus
            # l'ancien fallback 1,0 s de ai_api_hotfix ne fournit aucune disponibilité
            # supplémentaire mais réintroduit exactement la course observée.
            if kind == "api_fallback" and recovery_available:
                hotfix_removed += 1
                continue

            ordinals[kind] += 1
            wrapper = _make_wrapper(bot, original, kind, ordinals[kind])
            bot.add_listener(wrapper, "on_message")
            wrapped.append(f"{kind}:{ordinals[kind]}")
    else:
        # Comportement déjà voulu par l'ancienne autorité : le service Railway secondaire
        # ne doit pas répondre aux messages naturels SentriX. Cette fois TOUS les chemins
        # passifs sont retirés, pas seulement Ai.on_message.
        hotfix_removed = counts.get("api_fallback", 0)

    durable = getattr(bot, "sentrix_durable_store", None)
    postgres_available = bool(getattr(durable, "pool", None))
    bot.passive_ai_single_reply_state = {
        "installed": True,
        "primary_service": primary_service,
        "responders_found": dict(counts),
        "responders_removed_before_reconcile": removed,
        "active_wrappers": wrapped,
        "hotfix_fallback_removed": hotfix_removed,
        "postgres_available": postgres_available,
        "claim_ttl_seconds": ai_reply_claim.CLAIM_TTL,
        "service_id": (os.getenv("RAILWAY_SERVICE_ID") or "").strip(),
        "service_name": (os.getenv("RAILWAY_SERVICE_NAME") or "").strip(),
        "last_message_id": None,
        "last_owner": None,
        "last_claim_mode": None,
        "last_result": None,
        "last_error": None,
        "updated_at": int(time.time()),
    }
    setattr(bot, _MARKER, True)

    logger.warning(
        "IA passive V2 : service_principal=%s responders=%s wrappers=%s "
        "fallback_hotfix_supprime=%s postgres=%s ttl=%ss",
        primary_service,
        dict(counts),
        wrapped,
        hotfix_removed,
        postgres_available,
        int(ai_reply_claim.CLAIM_TTL),
    )


__all__ = [
    "install",
    "_is_primary_service",
    "_identity",
    "_explicit_trigger",
    "_should_coordinate",
]
