"""Protection de sortie logs pour SentriX sur Railway.

Python importe automatiquement ``sitecustomize`` au demarrage (sauf ``-S``). Le garde
est volontairement limite a Railway : en local et dans les tests, la configuration de
logging historique reste inchangee.

Objectifs :
- conserver toutes les erreurs importantes ;
- reduire les bibliotheques tierces tres bavardes ;
- empecher une boucle INFO/WARNING identique de depasser la limite de logs Railway ;
- ignorer uniquement les faux positifs connus d'un standby HA volontairement non connecte ;
- installer le routage dashboard leader-aware avant la construction aiohttp.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from dataclasses import dataclass


_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def _running_on_railway() -> bool:
    return any(name.startswith("RAILWAY_") for name in os.environ)


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _truthy_env(name: str) -> bool:
    return (os.getenv(name, "") or "").strip().lower() in {"1", "true", "yes", "on"}


def _expected_ha_standby_not_ready(record: logging.LogRecord, message: str) -> bool:
    """Reconnait le faux ERROR V45 attendu sur une instance standby passive.

    Le standby HA doit rester vivant sans ouvrir Discord tant que le primary detient le
    lease Redis. L'ancien audit V45, concu avant le failover, considere encore cette
    absence de on_ready apres 90 s comme une erreur. On ne masque ce message que lorsque
    le mode HA est explicitement actif ET que l'instance est explicitement standby.
    """
    if not _truthy_env("SENTRIX_FAILOVER_ENABLED"):
        return False
    if (os.getenv("SENTRIX_FAILOVER_ROLE", "") or "").strip().lower() != "standby":
        return False
    return (
        record.name == "bot.dashboard.health-runtime-v45"
        and "Discord n'est pas devenu pret en 90 secondes" in message
    )


@dataclass
class _RepeatState:
    started_at: float
    count: int = 0


class _RailwayFloodFilter(logging.Filter):
    """Laisse passer les vraies ERROR+, mais bride les floods de faible priorite."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._second_started = time.monotonic()
        self._low_priority_count = 0
        self._repeats: dict[tuple[str, int, str], _RepeatState] = {}

        # Railway avait deja signale 500 logs/s. On reste tres loin dessous tout en
        # gardant assez de marge pour observer un demarrage charge de SentriX.
        self._max_low_priority_per_second = _env_int(
            "SENTRIX_LOG_MAX_PER_SECOND", 100, 20, 300
        )
        self._repeat_window = _env_int("SENTRIX_LOG_REPEAT_WINDOW", 10, 2, 60)
        self._info_repeat_limit = _env_int("SENTRIX_LOG_INFO_REPEAT_LIMIT", 6, 1, 50)
        self._warning_repeat_limit = _env_int(
            "SENTRIX_LOG_WARNING_REPEAT_LIMIT", 20, 2, 100
        )

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)

        # Le standby passif n'est volontairement pas connecte a Discord. L'audit V45
        # historique produit alors un faux ERROR apres 90 s : on ignore uniquement ce cas
        # precisement identifie, sans toucher aux autres erreurs.
        if _expected_ha_standby_not_ready(record, message):
            return False

        # Une vraie erreur ne doit jamais etre cachee par le garde anti-flood.
        if record.levelno >= logging.ERROR:
            return True

        now = time.monotonic()
        key = (record.name, record.levelno, message)

        with self._lock:
            # Fenetre globale d'une seconde pour DEBUG/INFO uniquement.
            if now - self._second_started >= 1.0:
                self._second_started = now
                self._low_priority_count = 0

            # Deduplication des messages strictement identiques. Les WARNING restent
            # visibles plus souvent que les INFO afin de ne pas masquer un incident.
            state = self._repeats.get(key)
            if state is None or now - state.started_at >= self._repeat_window:
                state = _RepeatState(started_at=now)
                self._repeats[key] = state
            state.count += 1

            repeat_limit = (
                self._warning_repeat_limit
                if record.levelno >= logging.WARNING
                else self._info_repeat_limit
            )
            if state.count > repeat_limit:
                return False

            if record.levelno < logging.WARNING:
                self._low_priority_count += 1
                if self._low_priority_count > self._max_low_priority_per_second:
                    return False

            # Nettoyage leger pour empecher le dictionnaire de grossir indefiniment.
            if len(self._repeats) > 5000:
                cutoff = now - self._repeat_window
                self._repeats = {
                    item_key: item_state
                    for item_key, item_state in self._repeats.items()
                    if item_state.started_at >= cutoff
                }

        return True


def _configure_railway_logging() -> None:
    if not _running_on_railway():
        return

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Installer notre handler avant l'import de main.py : son logging.basicConfig()
    # devient alors volontairement un no-op et on evite plusieurs handlers identiques.
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(handler)

    flood_filter = _RailwayFloodFilter()
    for handler in root.handlers:
        if not any(isinstance(current, _RailwayFloodFilter) for current in handler.filters):
            handler.addFilter(flood_filter)

    # Ces bibliotheques peuvent produire enormement de details reseau au niveau INFO.
    # Les WARNING/ERROR restent integralement disponibles.
    for logger_name in (
        "aiohttp.access",
        "aiosqlite",
        "asyncio",
        "discord.gateway",
        "discord.http",
        "httpcore",
        "httpx",
        "openai",
        "urllib3",
    ):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def _install_railway_dashboard_ha_proxy() -> None:
    """Branche le proxy avant que railway_boot construise l'application dashboard."""
    if not _running_on_railway() or not _truthy_env("SENTRIX_FAILOVER_ENABLED"):
        return
    try:
        from web import dashboard as dashboard_web
        from web.dashboard_ha_proxy_v1 import install

        install(dashboard_web)
    except Exception:
        # Un probleme de proxy ne doit jamais empecher le bot Discord de demarrer. L'erreur
        # reste visible dans les logs Railway afin d'etre diagnostiquee.
        logging.getLogger("bot.dashboard-ha-proxy").exception(
            "Installation precoce du proxy dashboard HA impossible."
        )


_configure_railway_logging()
_install_railway_dashboard_ha_proxy()
