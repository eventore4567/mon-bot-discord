"""Recherche par texte libre ("titre + artiste", sans URL) — dernier recours dans
l'ordre de détection du ProviderManager (matches() toujours vrai : c'est la
plateforme "aucune URL reconnue"). Interroge plusieurs providers de LECTURE
(YouTube, SoundCloud...) en parallèle et laisse matcher.py choisir le meilleur
candidat plutôt que de prendre le premier résultat venu.

Ce même mécanisme (interroger les providers de lecture + matcher.py) est aussi
utilisé directement par le ProviderManager pour la 2ᵉ étape du pipeline Spotify/
Deezer (métadonnées connues -> trouver une source de lecture) — voir manager.py.
Ce module n'est qu'une façade pratique pour le cas "texte libre, rien connu du
tout" ; il ne duplique aucune logique d'extraction."""
from __future__ import annotations

import asyncio
import logging

from .. import matcher
from ..errors import NoPlayableSource
from ..models import Track
from .base import MusicProvider

logger = logging.getLogger("bot.music.provider.search")


class SearchProvider(MusicProvider):
    name = "search"
    can_provide_playback = True  # via les providers de lecture qu'on lui injecte
    can_search_by_text = True

    def __init__(self, playback_providers: list[MusicProvider]):
        super().__init__()
        self._playback_providers = playback_providers

    def matches(self, query: str) -> bool:
        # Catch-all : le ProviderManager ne l'essaie qu'après tous les providers à
        # URL explicite (voir manager.py::PLATFORM_PROVIDERS, vérifiés en premier).
        return True

    async def resolve_metadata(self, query: str, *, requested_by: int | None = None) -> list[Track]:
        target = Track(title=query.strip(), requested_by=requested_by, provider=self.name)
        candidates = await gather_candidates(self._playback_providers, title=query.strip(), artist=None, duration=None)
        best = matcher.pick_best(target, candidates, original_query=query)
        if best is None:
            raise NoPlayableSource(query, [p.name for p in self._playback_providers])
        best.requested_by = requested_by
        return [best]


async def gather_candidates(
    playback_providers: list[MusicProvider],
    *,
    title: str,
    artist: str | None,
    duration: int | None,
    limit: int = 5,
) -> list[Track]:
    """Interroge tous les providers de lecture disponibles (ni en cooldown, ni
    marqués indisponibles) EN PARALLÈLE et agrège leurs candidats. Un provider qui
    échoue (ProviderUnavailable) ne bloque jamais les autres — logué, pas propagé."""
    usable = [p for p in playback_providers if not p.is_temporarily_unavailable]

    async def _search_one(provider: MusicProvider) -> list[Track]:
        try:
            results = await provider.search_playable(title=title, artist=artist, duration=duration, limit=limit)
            provider.mark_available()
            logger.info("music playback candidate -> %s (%d résultat(s))", provider.name, len(results))
            return results
        except Exception as exc:
            from ..errors import ProviderUnavailable

            if isinstance(exc, ProviderUnavailable):
                provider.mark_unavailable(exc.reason)
            logger.info("music candidate rejected -> %s (%s)", provider.name, exc)
            return []

    results = await asyncio.gather(*(_search_one(p) for p in usable))
    candidates: list[Track] = []
    for batch in results:
        candidates.extend(batch)
    return candidates
