"""Rend la cession HA standby -> primary consciente des sessions musique actives.

Le failover d'urgence reste strict : une perte de lease ferme toujours Discord
immédiatement. Seule la cession *planifiée* d'un standby sain vers un primary qui
attend est différée tant qu'une session musique est réellement active.
"""
from __future__ import annotations

import logging
from typing import Any

from utils.failover import SentriXFailoverCoordinator

logger = logging.getLogger("bot.ha-music-drain")

_ORIGINAL_START_WATCHDOG = SentriXFailoverCoordinator.start_watchdog
_ORIGINAL_PRIMARY_WAITING = SentriXFailoverCoordinator.un_primary_attend


def _voice_connected(vc: Any) -> bool:
    try:
        return bool(vc and vc.is_connected())
    except Exception:
        return False


def music_activity_blocks_handoff(bot: Any) -> bool:
    """Vrai uniquement si une session musique doit survivre à la cession planifiée.

    Un simple client vocal connecté mais inactif ne bloque pas le retour au primary.
    Une lecture/pause Discord, ou une queue Music connectée avec piste actuelle / titres
    en attente, bloque la cession afin de ne pas couper l'audio en plein morceau.
    """
    if bot is None:
        return False

    try:
        voice_clients = getattr(bot, "voice_clients", ()) or ()
    except Exception:
        voice_clients = ()

    for vc in voice_clients:
        if not _voice_connected(vc):
            continue
        try:
            if vc.is_playing() or vc.is_paused():
                return True
        except Exception:
            continue

    try:
        cog = bot.get_cog("Music") if hasattr(bot, "get_cog") else None
    except Exception:
        cog = None

    try:
        queues = getattr(cog, "queues", {}) or {}
        values = queues.values() if hasattr(queues, "values") else ()
    except Exception:
        values = ()

    for queue in values:
        try:
            vc = getattr(queue, "voice_client", None)
            if not _voice_connected(vc):
                continue
            if getattr(queue, "current", None) is not None:
                return True
            if bool(getattr(queue, "tracks", None)):
                return True
        except Exception:
            continue

    return False


async def _primary_waiting_drain_aware(self: SentriXFailoverCoordinator) -> bool:
    waiting = await _ORIGINAL_PRIMARY_WAITING(self)
    if not waiting:
        self._sentrix_music_handoff_deferred = False
        return False

    bot = getattr(self, "_sentrix_watchdog_bot", None)
    if bot is None:
        # Compatibilité fail-safe : si le watchdog historique n'a pas fourni le bot,
        # on conserve exactement la décision HA d'origine plutôt que de bloquer la cession.
        return True

    if music_activity_blocks_handoff(bot):
        if not getattr(self, "_sentrix_music_handoff_deferred", False):
            logger.warning(
                "HA: cession standby -> primary différée : session musique active."
            )
        self._sentrix_music_handoff_deferred = True
        return False

    if getattr(self, "_sentrix_music_handoff_deferred", False):
        logger.warning(
            "HA: session musique terminée — cession standby -> primary de nouveau autorisée."
        )
    self._sentrix_music_handoff_deferred = False
    return True


def _start_watchdog_drain_aware(self: SentriXFailoverCoordinator, bot: Any):
    self._sentrix_watchdog_bot = bot
    return _ORIGINAL_START_WATCHDOG(self, bot)


def install() -> bool:
    cls = SentriXFailoverCoordinator
    if getattr(cls, "_sentrix_ha_music_drain", False):
        return True

    cls.start_watchdog = _start_watchdog_drain_aware
    cls.un_primary_attend = _primary_waiting_drain_aware
    cls._sentrix_ha_music_drain = True
    logger.info(
        "HA music drain actif : les cessions planifiées attendent la fin des sessions musique."
    )
    return True
