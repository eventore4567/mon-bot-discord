"""Interface commune à tous les providers musicaux — voir utils/music/__init__.py
pour l'architecture générale."""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod

from ..models import Track

logger = logging.getLogger("bot.music.provider")

# Après un ProviderUnavailable (challenge anti-bot, rate-limit), on n'insiste pas
# immédiatement sur le même provider pour la requête SUIVANTE — le cooldown lui
# laisse le temps de se rétablir sans bloquer toutes les lectures en attendant.
UNAVAILABLE_COOLDOWN_SECONDS = 120


class MusicProvider(ABC):
    """Un provider gère UNE plateforme. `can_provide_playback=False` signifie
    "métadonnées uniquement" (Spotify, Deezer) : ce provider ne fournit jamais de
    playable_url lui-même, le ProviderManager doit chercher une source de lecture
    ailleurs via le matching."""

    name: str
    can_provide_playback: bool = False
    can_search_by_text: bool = False  # utilisable pour "titre + artiste" sans URL

    def __init__(self):
        self._unavailable_until: float = 0.0

    @property
    def is_temporarily_unavailable(self) -> bool:
        return time.monotonic() < self._unavailable_until

    def mark_unavailable(self, reason: str) -> None:
        self._unavailable_until = time.monotonic() + UNAVAILABLE_COOLDOWN_SECONDS
        logger.warning(
            "music provider marked unavailable -> %s (%ss cooldown) reason=%s",
            self.name, UNAVAILABLE_COOLDOWN_SECONDS, reason,
        )

    def mark_available(self) -> None:
        self._unavailable_until = 0.0

    @abstractmethod
    def matches(self, query: str) -> bool:
        """True si cette query est une URL que CE provider reconnaît explicitement."""

    async def resolve_metadata(self, query: str, *, requested_by: int | None = None) -> list[Track]:
        """Résout une URL reconnue (matches()==True) en une ou plusieurs pistes
        (playlist). Lève TrackNotFound / ProviderUnavailable. Non abstraite : un
        provider purement "recherche" (SearchProvider) n'a pas d'URL propre."""
        raise NotImplementedError(f"{self.name} ne résout pas d'URL directe")

    async def search_playable(
        self, *, title: str, artist: str | None, duration: int | None, limit: int = 5,
    ) -> list[Track]:
        """Pour un provider can_provide_playback=True : cherche des candidats de
        LECTURE (playable_url déjà rempli) correspondant approximativement à la
        cible. Le classement fin est fait par matcher.py, pas ici — ce provider peut
        renvoyer plusieurs candidats bruts. Lève ProviderUnavailable si bloqué."""
        raise NotImplementedError(f"{self.name} ne supporte pas la recherche")

    async def refresh_playable_url(self, track: Track) -> str:
        """Ré-résout une URL de flux fraîche juste avant lecture (les URLs signées
        yt-dlp/SoundCloud expirent après un moment) à partir de track.original_url.
        Par défaut, réutilise playable_url tel quel (cas de l'audio direct)."""
        if not track.playable_url:
            raise RuntimeError(f"{self.name}: refresh_playable_url appelé sans playable_url existant")
        return track.playable_url
