"""Éviter que des événements Gateway dupliqués gonflent artificiellement l'anti-raid.

Discord peut retransmettre une notification de join lors d'une reconnexion.
Celle-ci ne doit pas compter comme un NOUVEAU membre et ne doit jamais
entraîner plusieurs kicks/timeouts/journaux pour une seule arrivée.

L'état est volontairement court (20 s) : un véritable rejoin ultérieur peut
être compté. Mémoire bornée, aucun ID conservé durablement.
"""
from __future__ import annotations

import time
from collections import OrderedDict


class RaidJoinDeduplicator:
    def __init__(self, *, ttl_seconds: float = 20.0, max_entries: int = 8192):
        if ttl_seconds <= 0 or max_entries <= 0:
            raise ValueError("Fenêtre et limite anti-raid doivent être positives")
        self.ttl_seconds = float(ttl_seconds)
        self.max_entries = int(max_entries)
        self._recent: OrderedDict[tuple[int, int], float] = OrderedDict()

    def first_join(self, guild_id: int, member_id: int, *, now: float | None = None) -> bool:
        tick = time.monotonic() if now is None else float(now)
        cutoff = tick - self.ttl_seconds

        while self._recent:
            oldest_key = next(iter(self._recent))
            if self._recent[oldest_key] > cutoff:
                break
            self._recent.popitem(last=False)

        key = (int(guild_id), int(member_id))
        prior = self._recent.get(key)
        if prior is not None and tick - prior <= self.ttl_seconds:
            return False

        self._recent[key] = tick
        self._recent.move_to_end(key)
        while len(self._recent) > self.max_entries:
            self._recent.popitem(last=False)
        return True

    def __len__(self) -> int:
        return len(self._recent)


__all__ = ["RaidJoinDeduplicator"]
