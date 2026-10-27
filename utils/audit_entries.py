"""Lire la cible d'une entrée du journal d'audit Discord sans planter.

discord.py lève TypeError dans ``AuditLogEntry.target`` quand l'entrée n'a pas de
cible (``int(None)`` dans Object) : ``getattr(entry, "target", None)`` ne protège
PAS, getattr ne rattrape que AttributeError. Production, 27/10/2026 : quatre
erreurs dans cogs.staff_suite (on_audit_log_entry_create) en une journée.
"""
from __future__ import annotations

from typing import Any


def cible(entry: Any) -> Any | None:
    try:
        return getattr(entry, "target", None)
    except (TypeError, ValueError):
        return None


def cible_id(entry: Any) -> int | None:
    brut = getattr(entry, "_target_id", None)
    if brut is not None:
        try:
            return int(brut)
        except (TypeError, ValueError):
            return None
    valeur = getattr(cible(entry), "id", None)
    return int(valeur) if valeur is not None else None


__all__ = ["cible", "cible_id"]
