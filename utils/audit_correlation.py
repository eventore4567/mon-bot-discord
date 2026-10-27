"""Corrélation prudente entre un événement Discord et son journal d'audit.

Une attribution n'est renvoyée que lorsque l'action, la cible et la fenêtre
temporelle concordent. Les petites relances compensent le retard habituel du
journal d'audit sans jamais prendre simplement sa dernière entrée.
"""
from __future__ import annotations

from utils import audit_entries

import asyncio
from dataclasses import dataclass
from typing import Callable

import discord


@dataclass(frozen=True)
class AuditCorrelation:
    actor: discord.abc.User | None
    entry: discord.AuditLogEntry | None
    status: str


def _target_id(entry: discord.AuditLogEntry) -> int | None:
    value = audit_entries.cible_id(entry)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def correlate_audit_entry(
    guild: discord.Guild,
    action: discord.AuditLogAction | None,
    *,
    target_id: int | None,
    max_age_seconds: float = 12.0,
    limit: int = 12,
    retry_delays: tuple[float, ...] = (0.0, 0.35, 0.9),
    extra_match: Callable[[discord.AuditLogEntry], bool] | None = None,
) -> AuditCorrelation:
    """Retourne une attribution seulement si toutes les preuves concordent."""
    me = getattr(guild, "me", None)
    permissions = getattr(me, "guild_permissions", None)
    if action is None:
        return AuditCorrelation(None, None, "action_indisponible")
    if me is None or permissions is None or not permissions.view_audit_log:
        return AuditCorrelation(None, None, "permission_manquante")

    wanted = int(target_id) if target_id is not None else None
    for delay in retry_delays:
        if delay:
            await asyncio.sleep(delay)
        now = discord.utils.utcnow()
        try:
            async for entry in guild.audit_logs(limit=limit, action=action):
                if wanted is not None and _target_id(entry) != wanted:
                    continue
                created_at = getattr(entry, "created_at", None)
                if created_at is None:
                    continue
                age = abs((now - created_at).total_seconds())
                if age > max_age_seconds:
                    continue
                if extra_match is not None and not extra_match(entry):
                    continue
                return AuditCorrelation(getattr(entry, "user", None), entry, "attribue")
        except (discord.Forbidden, discord.HTTPException):
            return AuditCorrelation(None, None, "journal_indisponible")
    return AuditCorrelation(None, None, "aucune_correspondance")


__all__ = ["AuditCorrelation", "correlate_audit_entry"]
