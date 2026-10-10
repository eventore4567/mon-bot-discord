"""Ce qu'un membre a vu la dernière fois — pour lui dire ce qui a changé depuis.

Quand un membre consulte SA fiche (+rank, +balance), SentriX garde les chiffres
affichés ; à la consultation suivante, la fiche dit l'écart : « +340 XP et
+1 niveau depuis votre dernier coup d'œil, il y a 2 j ». Rien n'est inventé :
la première consultation n'affiche rien, un écart nul récent non plus.
"""
from __future__ import annotations

import json
import time
from typing import Any

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS sentrix_last_seen ("
    "guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, key TEXT NOT NULL, "
    "snapshot TEXT NOT NULL, seen_at INTEGER NOT NULL, PRIMARY KEY (guild_id, user_id, key))"
)

#: Un écart nul n'est signalé qu'après ce délai (« rien de neuf depuis… »).
QUIET_SECONDS = 86400


async def remember(db: Any, guild_id: int, user_id: int, key: str, snapshot: dict[str, int],
                   *, now: float | None = None) -> tuple[dict[str, int], int] | None:
    """Enregistre ``snapshot`` et rend (écarts, secondes écoulées) depuis la fois
    d'avant — ou None la première fois ou si la mémoire est illisible."""
    now = int(now if now is not None else time.time())
    try:
        await db.execute(SCHEMA)
        row = await db.fetchone(
            "SELECT snapshot, seen_at FROM sentrix_last_seen WHERE guild_id = ? AND user_id = ? AND key = ?",
            (int(guild_id), int(user_id), key),
        )
        await db.execute(
            "INSERT INTO sentrix_last_seen (guild_id, user_id, key, snapshot, seen_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id, key) DO UPDATE SET snapshot = excluded.snapshot, seen_at = excluded.seen_at",
            (int(guild_id), int(user_id), key, json.dumps(snapshot, separators=(",", ":")), now),
        )
    except Exception:  # noqa: BLE001 — une fiche ne doit jamais casser pour sa mémoire
        return None
    if row is None:
        return None
    try:
        before = json.loads(row["snapshot"])
    except (TypeError, ValueError):
        return None
    deltas = {name: int(value) - int(before[name]) for name, value in snapshot.items()
              if isinstance(before.get(name), int)}
    return deltas, max(0, now - int(row["seen_at"] or now))


def _age(seconds: int, english: bool) -> str:
    if seconds >= 86400:
        return f"{seconds // 86400} {'d' if english else 'j'}"
    if seconds >= 3600:
        return f"{seconds // 3600} h"
    return f"{max(1, seconds // 60)} min"


def _signed(value: int, unit: str) -> str:
    number = f"{abs(int(value)):,}".replace(",", " ")
    return f"{'+' if value > 0 else '−'}{number} {unit}".rstrip()


def sentence(parts: list[str], seconds: int, *, english: bool = False) -> str:
    """« +340 XP, +1 niveau depuis votre dernier coup d'œil, il y a 2 j » — ou ""."""
    age = _age(seconds, english)
    if parts:
        joined = ", ".join(parts)
        return f"{joined} since you last checked, {age} ago" if english else (
            f"{joined} depuis votre dernier coup d'œil, il y a {age}"
        )
    if seconds >= QUIET_SECONDS:
        return f"Nothing new since you last checked, {age} ago" if english else (
            f"Rien de neuf depuis votre dernier coup d'œil, il y a {age}"
        )
    return ""


def level_parts(deltas: dict[str, int], *, english: bool = False) -> list[str]:
    parts = []
    if deltas.get("xp"):
        parts.append(_signed(deltas["xp"], "XP"))
    levels = deltas.get("level", 0)
    if levels:
        word = ("level" if abs(levels) == 1 else "levels") if english else ("niveau" if abs(levels) == 1 else "niveaux")
        parts.append(_signed(levels, word))
    places = -deltas.get("rank", 0)  # un rang qui baisse = des places gagnées
    if places:
        word = ("place" if abs(places) == 1 else "places") if english else ("place" if abs(places) == 1 else "places")
        parts.append(_signed(places, word) + (" on the leaderboard" if english else " au classement"))
    return parts


def money_parts(deltas: dict[str, int], unit: str) -> list[str]:
    return [_signed(deltas["money"], unit)] if deltas.get("money") else []


__all__ = ["QUIET_SECONDS", "SCHEMA", "level_parts", "money_parts", "remember", "sentence"]
