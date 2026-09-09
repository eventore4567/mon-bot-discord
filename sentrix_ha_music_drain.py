"""Rend la cession HA standby -> primary consciente de la présence vocale persistante.

Le failover d'urgence reste strict : une perte de lease ferme toujours Discord
immédiatement. Seule la cession *planifiée* d'un standby sain vers un primary qui
attend est différée tant que SentriX doit rester dans un salon vocal.

Depuis V104, une présence vocale épinglée doit survivre indéfiniment jusqu'à
``/music leave``. Un handoff HA planifié provoquerait forcément une courte
coupure vocale entre les deux processus Discord ; on l'interdit donc tant qu'une
session vocale persistante existe, même si aucune musique n'est en lecture.
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


def _voice_attached(vc: Any) -> bool:
    """Vrai si un VoiceClient représente encore une session vocale à préserver.

    Pendant une micro-reconnexion Discord, ``is_connected()`` peut brièvement être faux
    alors que ``channel`` est toujours renseigné. Cette fenêtre ne doit pas autoriser
    un handoff HA qui transformerait une reconnexion réseau en vraie coupure volontaire.
    """
    if vc is None:
        return False
    if _voice_connected(vc):
        return True
    try:
        return getattr(vc, "channel", None) is not None
    except Exception:
        return False


def music_activity_blocks_handoff(bot: Any) -> bool:
    """Vrai si une présence vocale SentriX doit survivre à la cession planifiée.

    Depuis V104, un client vocal simplement connecté et inactif est une session valide :
    SentriX doit rester dans le salon jusqu'à ``/music leave``. On bloque donc aussi les
    handoffs entre les pistes et lorsque la queue est vide. Les coupures d'urgence
    (perte du lease/processus) ne passent pas par cette fonction et restent inchangées.
    """
    if bot is None:
        return False

    try:
        voice_clients = getattr(bot, "voice_clients", ()) or ()
    except Exception:
        voice_clients = ()

    # Une présence vocale réelle suffit désormais à bloquer une cession planifiée.
    for vc in voice_clients:
        if _voice_attached(vc):
            return True

    try:
        cog = bot.get_cog("Music") if hasattr(bot, "get_cog") else None
    except Exception:
        cog = None

    # Le cache V104 garde l'intention de présence même pendant une micro-coupure où le
    # VoiceClient n'est momentanément plus visible dans bot.voice_clients.
    try:
        persistent = getattr(cog, "_sentrix_persistent_voice", None)
        if persistent is not None and bool(getattr(persistent, "has_pins", False)):
            return True
    except Exception:
        pass

    # Compatibilité avec une queue en cours de reconstruction avant que le cache V104
    # ne soit disponible. On conserve la logique historique comme filet de sécurité.
    try:
        queues = getattr(cog, "queues", {}) or {}
        values = queues.values() if hasattr(queues, "values") else ()
    except Exception:
        values = ()

    for queue in values:
        try:
            vc = getattr(queue, "voice_client", None)
            if _voice_attached(vc):
                return True
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
                "HA: cession standby -> primary différée : présence vocale persistante active."
            )
        self._sentrix_music_handoff_deferred = True
        return False

    if getattr(self, "_sentrix_music_handoff_deferred", False):
        logger.warning(
            "HA: aucune présence vocale persistante — cession standby -> primary de nouveau autorisée."
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
        "HA voice drain actif : les cessions planifiées sont bloquées tant qu'une présence vocale V104 est épinglée."
    )
    return True
