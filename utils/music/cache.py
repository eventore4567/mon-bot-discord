"""Cache TTL en mémoire pour les résolutions de métadonnées et de lecture — évite de
refaire la même recherche à chaque commande (demande explicite). Volontairement
simple (process-local, non persistant) : les métadonnées d'un morceau ne changent
pas d'une minute à l'autre, et la lecture réelle interroge yt-dlp de toute façon
juste avant de jouer (les URLs de flux expirent — voir providers/youtube.py)."""
from __future__ import annotations

import time
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")

METADATA_TTL = 6 * 3600  # les infos titre/artiste/durée ne bougent pas
SEARCH_TTL = 30 * 60     # un résultat de recherche peut légitimement changer (nouvelles vidéos)


class TTLCache:
    def __init__(self):
        self._store: dict[str, tuple[float, object]] = {}

    def get(self, key: str):
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < time.monotonic():
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value, ttl: float) -> None:
        self._store[key] = (time.monotonic() + ttl, value)

    async def get_or_fetch(self, key: str, ttl: float, fetcher: Callable[[], Awaitable[T]]) -> T:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = await fetcher()
        self.set(key, value, ttl)
        return value

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()
