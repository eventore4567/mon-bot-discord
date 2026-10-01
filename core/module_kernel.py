"""Micro-kernel SentriX : registre minimal de santé des modules.

Le noyau ne connaît aucune logique métier Discord. Il suit uniquement l'état de
chargement des extensions afin qu'un module optionnel en panne reste isolé et
observable sans rendre tout le bot indisponible.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterable


@dataclass(slots=True)
class ModuleState:
    name: str
    critical: bool = False
    status: str = "pending"
    load_ms: float | None = None
    error: str | None = None
    attempts: int = 0
    _started_at: float | None = field(default=None, repr=False)

    def begin(self) -> None:
        self.attempts += 1
        self.status = "loading"
        self.error = None
        self._started_at = time.perf_counter()

    def finish(self, *, error: BaseException | None = None) -> None:
        if self._started_at is not None:
            self.load_ms = round((time.perf_counter() - self._started_at) * 1000, 2)
        self._started_at = None
        if error is None:
            self.status = "loaded"
            self.error = None
        else:
            self.status = "failed"
            self.error = type(error).__name__


class ModuleKernel:
    """Petit registre d'état, indépendant des cogs et de Discord."""

    def __init__(self, modules: Iterable[str], critical: Iterable[str] = ()) -> None:
        critical_set = set(critical)
        self._states = {
            name: ModuleState(name=name, critical=name in critical_set)
            for name in modules
        }

    def begin(self, name: str) -> None:
        self._states[name].begin()

    def loaded(self, name: str) -> None:
        self._states[name].finish()

    def failed(self, name: str, error: BaseException) -> None:
        self._states[name].finish(error=error)

    def snapshot(self) -> dict:
        rows = list(self._states.values())
        failed = [
            {"name": row.name, "error": row.error or "UnknownError", "critical": row.critical}
            for row in rows
            if row.status == "failed"
        ]
        critical_failed = sorted(item["name"] for item in failed if item["critical"])
        loaded = sum(row.status == "loaded" for row in rows)
        return {
            "expected": len(rows),
            "loaded": loaded,
            "failed": failed,
            "critical_failed": critical_failed,
            "ready": not critical_failed,
            "modules": {
                row.name: {
                    "status": row.status,
                    "critical": row.critical,
                    "load_ms": row.load_ms,
                    "error": row.error,
                    "attempts": row.attempts,
                }
                for row in rows
            },
        }
