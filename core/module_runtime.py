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
    def __init__(
        self,
        bot,
        kernel,
        *,
        locked: Iterable[str] = (),
        operation_timeout_seconds: float = 20.0,
    ) -> None:
        self.bot = bot
        self.kernel = kernel
        self.locked = frozenset(locked)
        self.operation_timeout_seconds = max(1.0, float(operation_timeout_seconds))
        self._lock = asyncio.Lock()
        self._last_operation: dict | None = None

    def snapshot(self) -> dict:
        return {
            "locked": sorted(self.locked),
            "busy": self._lock.locked(),
            "operation_timeout_seconds": self.operation_timeout_seconds,
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

    async def _bounded(self, awaitable):
        return await asyncio.wait_for(
            awaitable,
            timeout=self.operation_timeout_seconds,
        )

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

    def _circuit_state(self, name: str) -> tuple[bool, str | None]:
        state = self.kernel.snapshot().get("modules", {}).get(name, {})
        return bool(state.get("circuit_open")), state.get("circuit_reason")

    def _restore_circuit(self, name: str, was_open: bool, reason: str | None, *, closed_reason: str) -> None:
        if was_open and hasattr(self.kernel, "open_circuit"):
            self.kernel.open_circuit(
                name,
                reason=str(reason or "runtime_errors"),
                replace_reason=True,
            )
        elif hasattr(self.kernel, "close_circuit"):
            self.kernel.close_circuit(name, reason=closed_reason)

    async def reload(self, name: str) -> dict:
        self._validate(name)
        async with self._lock:
            dependents = tuple(
                dep
                for dep in getattr(self.kernel, "dependents", lambda _name: ()) (name)
                if dep in self.bot.extensions
            )
            locked_dependents = [dep for dep in dependents if dep in self.locked]
            if locked_dependents:
                raise RuntimeError(
                    f"Reload bloqué : dépendant protégé pour {name}: {', '.join(locked_dependents)}"
                )

            primary_was_loaded = name in self.bot.extensions
            primary_circuit = self._circuit_state(name)
            dependent_circuits = {
                dep: self._circuit_state(dep)
                for dep in dependents
            }

            if hasattr(self.kernel, "open_circuit"):
                self.kernel.open_circuit(
                    name,
                    reason="maintenance",
                    replace_reason=True,
                )
                for dep in dependents:
                    self.kernel.open_circuit(
                        dep,
                        reason=f"dependency_reload:{name}",
                        replace_reason=True,
                    )

            drain_targets = (name, *dependents)
            busy = {}
            for target in drain_targets:
                remaining = await self._wait_for_drain(target)
                if remaining:
                    busy[target] = remaining

            if busy:
                self._restore_circuit(
                    name,
                    primary_circuit[0],
                    primary_circuit[1],
                    closed_reason="drain_timeout",
                )
                for dep, previous in dependent_circuits.items():
                    self._restore_circuit(
                        dep,
                        previous[0],
                        previous[1],
                        closed_reason="dependency_drain_timeout",
                    )
                self._last_operation = {
                    "operation": "reload",
                    "module": name,
                    "ok": False,
                    "error": "ModuleBusy",
                    "busy": dict(busy),
                }
                self.refresh()
                raise RuntimeError(f"Module occupé pendant le reload: {name}")

            self.kernel.begin(name, operation="reload")
            try:
                if primary_was_loaded:
                    await self._bounded(self.bot.reload_extension(name))
                else:
                    await self._bounded(self.bot.load_extension(name))
            except Exception as exc:
                if primary_was_loaded and name in self.bot.extensions:
                    self.kernel.recovered(name, exc)
                    self._restore_circuit(
                        name,
                        primary_circuit[0],
                        primary_circuit[1],
                        closed_reason="rollback",
                    )
                else:
                    self.kernel.failed(name, exc)

                for dep, previous in dependent_circuits.items():
                    self._restore_circuit(
                        dep,
                        previous[0],
                        previous[1],
                        closed_reason="dependency_parent_rollback",
                    )

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

            dependent_failures: list[dict[str, str]] = []
            for dep in dependents:
                self.kernel.begin(dep, operation="reload")
                try:
                    await self._bounded(self.bot.reload_extension(dep))
                except Exception as exc:
                    if dep in self.bot.extensions:
                        self.kernel.recovered(dep, exc)
                        self.kernel.record_runtime_error(
                            dep,
                            "DependencyReloadFailed",
                            threshold=1,
                            circuit_threshold=999999,
                        )
                    else:
                        self.kernel.failed(dep, exc)

                    previous = dependent_circuits[dep]
                    if previous[0]:
                        self.kernel.open_circuit(
                            dep,
                            reason=str(previous[1] or "runtime_errors"),
                            replace_reason=True,
                        )
                    else:
                        self.kernel.open_circuit(
                            dep,
                            reason="dependency_reload_failed",
                            replace_reason=True,
                        )
                    dependent_failures.append({
                        "module": dep,
                        "error": type(exc).__name__,
                    })
                    logger.exception(
                        "Micro-kernel : reload dépendant échoué %s après %s.",
                        dep,
                        name,
                    )
                    continue

                self.kernel.loaded(dep)
                if hasattr(self.kernel, "close_circuit"):
                    self.kernel.close_circuit(dep, reason="dependency_reload_success")

            self._last_operation = {
                "operation": "reload",
                "module": name,
                "ok": True,
                "error": None,
                "dependents": list(dependents),
                "dependent_failures": dependent_failures,
            }
            return self.refresh()

    async def recover_missing(self, name: str) -> dict:
        """Récupère uniquement une extension absente, y compris critique.

        Cette voie ne reload/unload jamais un module déjà actif. Elle permet de
        réparer un échec de boot critique sans prendre de risque sur une fonction
        critique qui fonctionne déjà.
        """
        if not self.kernel.contains(name):
            raise ValueError(f"Extension inconnue: {name}")

        async with self._lock:
            if name in self.bot.extensions:
                return self.refresh()

            blockers = self.kernel.blockers(name)
            if blockers:
                self.kernel.blocked(name, blockers)
                return self.refresh()

            self.kernel.begin(name, operation="recovery-load")
            try:
                await self._bounded(self.bot.load_extension(name))
            except Exception as exc:
                self.kernel.failed(name, exc)
                self._last_operation = {
                    "operation": "recovery-load",
                    "module": name,
                    "ok": False,
                    "error": type(exc).__name__,
                }
                self.refresh()
                raise

            self.kernel.loaded(name)
            self._last_operation = {
                "operation": "recovery-load",
                "module": name,
                "ok": True,
                "error": None,
            }
            return self.refresh()

    async def stop(self, name: str) -> dict:
        self._validate(name)
        async with self._lock:
            active_dependents = [
                dep
                for dep in getattr(self.kernel, "dependents", lambda _name: ()) (name)
                if dep in self.bot.extensions
            ]
            if active_dependents:
                self._last_operation = {
                    "operation": "stop",
                    "module": name,
                    "ok": False,
                    "error": "ActiveDependents",
                    "dependents": list(active_dependents),
                }
                raise RuntimeError(
                    f"Arrêt refusé : {name} est requis par {', '.join(active_dependents)}"
                )

            try:
                if name in self.bot.extensions:
                    await self._bounded(self.bot.unload_extension(name))
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
