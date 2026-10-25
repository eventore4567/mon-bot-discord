"""Mesures légères d'ouverture de ticket, sans modifier l'ordre des actions.

Sépare la latence de confirmation visible du temps d'écriture des journaux.
Aucune réponse, contenu de ticket ou donnée privée n'entre dans le rapport.
"""
from __future__ import annotations

import time
from collections.abc import Callable


class TicketOpenTimings:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._started = self._previous = self._clock()
        self.stages_ms: dict[str, float] = {}
        self.confirmed_ms: float | None = None

    def mark(self, stage: str) -> float:
        now = self._clock()
        duration = max(0.0, (now - self._previous) * 1000)
        self.stages_ms[stage] = round(duration, 1)
        self._previous = now
        return duration

    def mark_confirmed(self) -> None:
        self.mark("user_confirmation")
        self.confirmed_ms = round(max(0.0, (self._previous - self._started) * 1000), 1)

    @property
    def total_ms(self) -> float:
        return round(max(0.0, (self._clock() - self._started) * 1000), 1)

    def summary(self) -> dict[str, float | None | dict[str, float]]:
        return {
            "confirmed_ms": self.confirmed_ms,
            "total_ms": self.total_ms,
            "stages_ms": dict(self.stages_ms),
        }
