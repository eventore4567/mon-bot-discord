"""Autorité finale : une seule réponse IA passive par message Discord.

Cette couche ne crée aucun cooldown. Deux messages Discord différents, même envoyés à la
même milliseconde, restent indépendants. Elle agit uniquement sur le listener naturel du
Cog ``cogs.ai.Ai`` :
- sur Railway, seul le service SentriX principal conserve ce listener ;
- sur le service principal, un seul callback ``Ai.on_message`` est enregistré ;
- le même ``message.id`` ne peut être traité qu'une fois dans le process.

Les commandes préfixées et slash ne sont pas touchées.
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
_RECENT_MESSAGE_IDS: dict[int, float] = {}
_MARKER = "_sentrix_passive_ai_single_reply_final"


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


def _claim_message(message) -> bool:
    try:
        message_id = int(message.id)
    except (AttributeError, TypeError, ValueError):
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


def install(bot: commands.Bot) -> None:
    """Réconcilie les listeners IA naturels après le chargement complet des cogs."""
    listeners = list((getattr(bot, "extra_events", {}) or {}).get("on_message", ()) or ())
    ai_listeners = [callback for callback in listeners if _is_ai_on_message(callback)]

    # On retire d'abord toutes les copies historiques. Les autres listeners on_message
    # (logs, automod, niveaux, etc.) restent strictement intacts.
    removed = 0
    for callback in ai_listeners:
        try:
            bot.remove_listener(callback, "on_message")
            removed += 1
        except (ValueError, TypeError):
            pass

    primary = _is_primary_service()
    installed_listener = False

    if primary and ai_listeners:
        original = ai_listeners[0]

        @functools.wraps(original)
        async def single_natural_listener(message):
            if not _claim_message(message):
                logger.info(
                    "Double traitement IA naturel bloqué — message=%s",
                    getattr(message, "id", "?"),
                )
                return None
            return await original(message)

        setattr(single_natural_listener, _MARKER, True)
        single_natural_listener._sentrix_original = original
        bot.add_listener(single_natural_listener, "on_message")
        installed_listener = True

    bot.passive_ai_single_reply_state = {
        "installed": True,
        "primary_service": primary,
        "ai_listeners_found": len(ai_listeners),
        "ai_listeners_removed": removed,
        "active_ai_listener": installed_listener,
        "service_id": (os.getenv("RAILWAY_SERVICE_ID") or "").strip(),
        "service_name": (os.getenv("RAILWAY_SERVICE_NAME") or "").strip(),
    }
    setattr(bot, _MARKER, True)

    if primary:
        logger.warning(
            "IA passive autorité finale : %s listener(s) Ai retiré(s), un seul listener actif.",
            removed,
        )
    else:
        logger.warning(
            "IA passive désactivée sur le service Railway secondaire : %s listener(s) Ai retiré(s).",
            removed,
        )


__all__ = ["install", "_is_primary_service", "_claim_message", "_is_ai_on_message"]
