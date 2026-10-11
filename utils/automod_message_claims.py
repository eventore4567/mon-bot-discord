"""Idempotence des sanctions automatiques par événement Discord.

Les listeners on_message de plusieurs cogs s'exécutent en parallèle.
Réserver l'ID d'un message de façon synchrone AVANT le premier await empêche
deux suppressions, avertissements, scores de risque et sanctions sur ce message.

Les ID Discord sont uniques et jamais réutilisés ; une réserve TTL brève suffit
pour le redéclenchement Gateway et les callbacks concurrents. État borné.
"""
from __future__ import annotations

from collections import OrderedDict
import time


class AutomodMessageClaims:
    def __init__(self, *, ttl_seconds: float = 120.0, max_entries: int = 16384):
        if ttl_seconds <= 0 or max_entries <= 0:
            raise ValueError("Automod message claim limits must be positive")
        self.ttl_seconds = float(ttl_seconds)
        self.max_entries = int(max_entries)
        self._claimed: OrderedDict[tuple[int, int], float] = OrderedDict()

    def claim(self, guild_id: int, message_id: int, *, now: float | None = None) -> bool:
        """Réserve immédiatement (sans await) un message ; False si déjà traité."""
        if not guild_id or not message_id:
            return False
        tick = time.monotonic() if now is None else float(now)
        cutoff = tick - self.ttl_seconds

        while self._claimed:
            oldest = next(iter(self._claimed))
            if self._claimed[oldest] > cutoff:
                break
            self._claimed.popitem(last=False)

        key = (int(guild_id), int(message_id))
        if key in self._claimed:
            return False

        self._claimed[key] = tick
        while len(self._claimed) > self.max_entries:
            self._claimed.popitem(last=False)
        return True

    def __len__(self) -> int:
        return len(self._claimed)


__all__ = ["AutomodMessageClaims"]
