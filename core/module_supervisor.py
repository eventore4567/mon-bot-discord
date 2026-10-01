"""Superviseur léger des modules optionnels SentriX.

Il ne redémarre jamais les modules critiques ni les modules volontairement arrêtés.
Seuls les échecs techniques d'extensions explicitement retryables sont retentés,
avec un budget borné et un backoff croissant.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Iterable

from discord.ext import tasks

logger = logging.getLogger("bot.module-supervisor")


class ModuleSupervisor:
    def __init__(
        self,
        retryable: Iterable[str],
        *,
        retry_delays: tuple[int, ...] = (60, 300, 900),
        scan_interval: int = 30,
    ) -> None:
        self.retryable = frozenset(retryable)
        self.retry_delays = tuple(max(1, int(v)) for v in retry_delays)
        self.scan_interval = max(5, int(scan_interval))
        self._failures: dict[str, int] = {}
        self._next_retry: dict[str, float] = {}
        self._recovered = 0
        self._last_recovered: str | None = None
        self._running = False
        self._failed_loops: set[str] = set()
        self._internal_errors = 0
        self._last_internal_error: str | None = None

    def snapshot(self) -> dict:
        now = time.monotonic()
        return {
            "running": self._running,
            "retryable_count": len(self.retryable),
            "recovered": self._recovered,
            "last_recovered": self._last_recovered,
            "failed_background_loops": sorted(self._failed_loops),
            "internal_errors": self._internal_errors,
            "last_internal_error": self._last_internal_error,
            "pending": {
                name: {
                    "failures": count,
                    "retry_in_seconds": max(
                        0,
                        round(self._next_retry.get(name, now) - now),
                    ),
                }
                for name, count in self._failures.items()
                if count > 0
            },
        }

    def _schedule_failure(self, name: str) -> None:
        count = self._failures.get(name, 0) + 1
        self._failures[name] = count
        if count <= len(self.retry_delays):
            self._next_retry[name] = time.monotonic() + self.retry_delays[count - 1]

    def _clear(self, name: str) -> None:
        self._failures.pop(name, None)
        self._next_retry.pop(name, None)

    def _scan_failed_loops(self, bot, kernel) -> None:
        current_failed: set[str] = set()
        for cog in getattr(bot, "cogs", {}).values():
            module_name = str(getattr(type(cog), "__module__", "") or "")
            if not module_name.startswith("cogs.") or not kernel.contains(module_name):
                continue
            for attr in dir(cog):
                if attr.startswith("__"):
                    continue
                try:
                    value = getattr(cog, attr)
                except Exception:
                    continue
                if not isinstance(value, tasks.Loop):
                    continue
                try:
                    failed = bool(value.failed())
                except Exception:
                    failed = False
                if not failed:
                    continue
                key = f"{module_name}:{type(cog).__name__}.{attr}"
                current_failed.add(key)
                if key not in self._failed_loops:
                    kernel.record_runtime_error(
                        module_name,
                        "BackgroundLoopFailed",
                        threshold=1,
                    )
                    logger.error(
                        "Micro-kernel : boucle de fond en échec détectée : %s",
                        key,
                    )
        self._failed_loops = current_failed

    async def _retry_one(self, bot, name: str) -> None:
        try:
            await bot.reload_runtime_module(name)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._schedule_failure(name)
            logger.exception(
                "Micro-kernel : récupération du module %s impossible (tentative %s/%s).",
                name,
                self._failures.get(name, 0),
                len(self.retry_delays),
            )
            return

        self._clear(name)
        self._recovered += 1
        self._last_recovered = name
        logger.warning("Micro-kernel : module optionnel récupéré automatiquement : %s", name)

    async def run(self, bot) -> None:
        self._running = True
        try:
            while not bot.is_closed():
                await asyncio.sleep(self.scan_interval)
                try:
                    kernel = getattr(bot, "module_kernel", None)
                    if kernel is None:
                        continue
                    refresh = getattr(bot, "_refresh_module_health", None)
                    snapshot = refresh() if callable(refresh) else kernel.snapshot()
                    self._scan_failed_loops(bot, kernel)
                    snapshot = refresh() if callable(refresh) else kernel.snapshot()
                    now = time.monotonic()
                    for name, state in snapshot.get("modules", {}).items():
                        if name not in self.retryable:
                            continue
                        status = state.get("status")

                        if status == "unloaded":
                            self._clear(name)
                            continue

                        if status == "blocked":
                            if kernel.blockers(name):
                                continue
                            await self._retry_one(bot, name)
                            continue

                        if status != "failed":
                            self._clear(name)
                            continue

                        failures = self._failures.get(name, 0)
                        if failures >= len(self.retry_delays):
                            continue
                        if now < self._next_retry.get(name, 0):
                            continue
                        await self._retry_one(bot, name)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._internal_errors += 1
                    self._last_internal_error = type(exc).__name__
                    logger.exception(
                        "Micro-kernel : erreur interne du superviseur, surveillance conservée."
                    )
        finally:
            self._running = False
