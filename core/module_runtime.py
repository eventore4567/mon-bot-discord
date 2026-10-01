"""Contrôleur de cycle de vie des modules SentriX.

Ce composant contient la mécanique runtime (reconcile/reload/unload) pour que le
bot principal reste un simple orchestrateur. Aucune logique métier de cog ici.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

logger = logging.getLogger("bot.module-runtime")


class ModuleRuntimeController:
    def __init__(self, bot, kernel, *, locked: Iterable[str] = ()) -> None:
        self.bot = bot
        self.kernel = kernel
        self.locked = frozenset(locked)
        self._lock = asyncio.Lock()
        self._last_operation: dict | None = None

    def snapshot(self) -> dict:
        return {
            "locked": sorted(self.locked),
            "busy": self._lock.locked(),
            "last_operation": dict(self._last_operation) if self._last_operation else None,
        }

    def refresh(self) -> dict:
        changed = self.kernel.reconcile(self.bot.extensions.keys())
        if changed:
            logger.warning(
                "Micro-kernel : état runtime réconcilié pour %s",
                ", ".join(changed),
            )
        snapshot = self.kernel.snapshot()
        self.bot._sentrix_extension_health = snapshot
        return snapshot

    def _validate(self, name: str) -> None:
        if not self.kernel.contains(name):
            raise ValueError(f"Extension inconnue: {name}")
        if name in self.locked:
            raise RuntimeError(f"Extension protégée: {name}")

    async def _wait_for_drain(self, name: str, *, timeout: float = 5.0) -> int:
        deadline = asyncio.get_running_loop().time() + max(0.1, float(timeout))
        while self.kernel.in_flight(name) > 0:
            if asyncio.get_running_loop().time() >= deadline:
                remaining = self.kernel.in_flight(name)
                logger.warning(
                    "Micro-kernel : drain incomplet pour %s, %s commande(s) encore active(s).",
                    name,
                    remaining,
                )
                return remaining
            await asyncio.sleep(0.05)
        return 0

    async def reload(self, name: str) -> dict:
        self._validate(name)
        async with self._lock:
            was_loaded = name in self.bot.extensions
            if hasattr(self.kernel, "open_circuit"):
                self.kernel.open_circuit(name, reason="maintenance")
            await self._wait_for_drain(name)
            self.kernel.begin(name, operation="reload")
            try:
                if was_loaded:
                    await self.bot.reload_extension(name)
                else:
                    await self.bot.load_extension(name)
            except Exception as exc:
                if was_loaded and name in self.bot.extensions:
                    self.kernel.recovered(name, exc)
                    if hasattr(self.kernel, "close_circuit"):
                        self.kernel.close_circuit(name, reason="rollback")
                else:
                    self.kernel.failed(name, exc)
                self._last_operation = {
                    "operation": "reload",
                    "module": name,
                    "ok": False,
                    "error": type(exc).__name__,
                }
                self.refresh()
                raise

            self.kernel.loaded(name)
            if hasattr(self.kernel, "close_circuit"):
                self.kernel.close_circuit(name, reason="reload_success")
            self._last_operation = {
                "operation": "reload",
                "module": name,
                "ok": True,
                "error": None,
            }
            return self.refresh()

    async def stop(self, name: str) -> dict:
        self._validate(name)
        async with self._lock:
            try:
                if name in self.bot.extensions:
                    await self.bot.unload_extension(name)
            except Exception as exc:
                self._last_operation = {
                    "operation": "stop",
                    "module": name,
                    "ok": False,
                    "error": type(exc).__name__,
                }
                raise

            self.kernel.unloaded(name)
            self._last_operation = {
                "operation": "stop",
                "module": name,
                "ok": True,
                "error": None,
            }
            return self.refresh()
