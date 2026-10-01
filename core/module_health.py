"""Fonctions pures de santé du micro-kernel SentriX.

Aucune dépendance Discord, dashboard ou variable secrète ici. Ce module est
explicitement importable pendant les builds et les tests unitaires.
"""
from __future__ import annotations

from typing import Any


USER_OR_EXPECTED_ERROR_NAMES = frozenset({
    "CommandNotFound",
    "BadArgument",
    "MissingRequiredArgument",
    "TooManyArguments",
    "MemberNotFound",
    "UserNotFound",
    "RoleNotFound",
    "ChannelNotFound",
    "CommandOnCooldown",
    "MissingPermissions",
    "BotMissingPermissions",
    "NoPrivateMessage",
    "CheckFailure",
    "Forbidden",
    "NotFound",
    "DisabledCommand",
    "MaxConcurrencyReached",
    "ModuleTemporarilyUnavailable",
    "AppModuleTemporarilyUnavailable",
})


def is_technical_failure(error: BaseException | str) -> bool:
    name = error if isinstance(error, str) else type(error).__name__
    return str(name) not in USER_OR_EXPECTED_ERROR_NAMES


def extension_state_from_runtime(
    runtime: dict[str, Any] | None,
    *,
    fallback_loaded: int,
    fallback_expected: int,
) -> tuple[int, int, bool, list[str], list[dict]]:
    if isinstance(runtime, dict):
        loaded = int(runtime.get("loaded") or 0)
        expected = int(runtime.get("expected") or loaded)
        critical_failed = [str(name) for name in (runtime.get("critical_failed") or [])]
        failed = [
            dict(item)
            for item in (runtime.get("failed") or [])
            if isinstance(item, dict)
        ]
        ready = bool(runtime.get("ready", not critical_failed))
        return loaded, expected, ready, critical_failed, failed

    return (
        int(fallback_loaded),
        int(fallback_expected),
        int(fallback_loaded) >= int(fallback_expected),
        [],
        [],
    )
