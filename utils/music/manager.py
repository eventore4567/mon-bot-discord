"""Le chef d'orchestre : requête -> détection de plateforme -> métadonnées ->
recherche de sources de lecture -> tentatives avec repli automatique. Voir
utils/music/__init__.py pour le schéma complet du pipeline.

Cette classe est volontairement indépendante de discord.py — cogs/music.py ne fait
que l'appeler et gérer la voix/FFmpeg/les embeds. Elle peut donc être testée sans
jamais toucher à Discord (voir tests/test_music_*.py)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import matcher
from .cache import METADATA_TTL, TTLCache
from .errors import NoPlayableSource, ProviderUnavailable, TrackNotFound
from .models import Track
from .providers import (
    DeezerProvider,
    DirectAudioProvider,
    MusicProvider,
    SearchProvider,
    SoundCloudProvider,
    SpotifyProvider,
    YouTubeProvider,
)
from .providers.search import gather_candidates

logger = logging.getLogger("bot.music.manager")


@dataclass
class ResolvedRequest:
    tracks: list[Track] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def is_playlist(self) -> bool:
        return len(self.tracks) > 1


class ProviderManager:
    def __init__(self, *, cache: TTLCache | None = None, providers: list[MusicProvider] | None = None):
        if providers is not None:
            self.direct, self.spotify, self.deezer, self.soundcloud, self.youtube = providers[:5]
            self.playback_providers = [p for p in providers if p.can_provide_playback and p is not self.direct]
        else:
            self.direct = DirectAudioProvider()
            self.spotify = SpotifyProvider()
            self.deezer = DeezerProvider()
            self.soundcloud = SoundCloudProvider()
            self.youtube = YouTubeProvider()
            self.playback_providers = [self.youtube, self.soundcloud]

        self.search = SearchProvider(self.playback_providers)
        self.platform_providers: list[MusicProvider] = [
            self.direct, self.spotify, self.deezer, self.soundcloud, self.youtube, self.search,
        ]
        self.cache = cache or TTLCache()

    def _detect_provider(self, query: str) -> MusicProvider:
        for provider in self.platform_providers:
            if provider.matches(query):
                return provider
        return self.search

    async def resolve(self, query: str, *, requested_by: int | None) -> ResolvedRequest:
        query = query.strip()
        if not query:
            raise TrackNotFound("input", query)

        provider = self._detect_provider(query)
        logger.info("music request -> %s", provider.name)

        cache_key = f"meta:{provider.name}:{query}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            raw_tracks: list[Track] = cached
        else:
            raw_tracks = await provider.resolve_metadata(query, requested_by=requested_by)
            if (not provider.can_provide_playback) or any(track.is_playable for track in raw_tracks):
                provider.mark_available()
            self.cache.set(cache_key, raw_tracks, METADATA_TTL)
        logger.info("metadata resolved -> %d piste(s) via %s", len(raw_tracks), provider.name)

        # Une playlist n'a pas besoin d'extraire/résoudre l'audio de 20-100 vidéos
        # pendant l'import. C'est précisément ce qui déclenchait le challenge
        # anti-bot YouTube sur Railway. On conserve les métadonnées et la résolution
        # de lecture se fait au moment où chaque titre démarre.
        if len(raw_tracks) > 1:
            prepared = [Track(**{**raw.__dict__, "requested_by": requested_by}) for raw in raw_tracks]
            logger.info("playlist metadata accepted -> %d piste(s), playback deferred", len(prepared))
            return ResolvedRequest(tracks=prepared, skipped=[])

        resolved: list[Track] = []
        skipped: list[str] = []
        for raw in raw_tracks:
            track = Track(**{**raw.__dict__, "requested_by": requested_by})
            if track.is_playable:
                resolved.append(track)
                continue

            candidates = await gather_candidates(
                self.playback_providers,
                title=track.title,
                artist=track.artist,
                duration=track.duration,
            )
            best = matcher.pick_best(track, candidates, original_query=query)
            if best is None:
                logger.warning("music no playback candidate -> %r", track.title)
                skipped.append(track.display_title())
                continue

            logger.info("playback started candidate -> %s", best.playback_provider)
            track.playable_url = best.playable_url
            track.playback_provider = best.playback_provider
            track.original_url = best.original_url or track.original_url
            resolved.append(track)

        if not resolved:
            attempted = [p.name for p in self.platform_providers if p is not self.search]
            raise NoPlayableSource(raw_tracks[0].title if raw_tracks else query, attempted)

        return ResolvedRequest(tracks=resolved, skipped=skipped)

    async def ensure_playable(self, track: Track) -> Track:
        """Résout à la demande une piste persistée qui ne possède pas encore d'audio."""
        if track.is_playable:
            return track

        query = " ".join(part for part in (track.artist, track.title) if part).strip() or track.title
        result = await self.resolve(query, requested_by=track.requested_by)
        if not result.tracks:
            raise NoPlayableSource(track.title, [p.name for p in self.playback_providers])

        best = result.tracks[0]
        track.playable_url = best.playable_url
        track.playback_provider = best.playback_provider
        track.original_url = best.original_url or track.original_url
        if not track.duration:
            track.duration = best.duration
        if not track.thumbnail:
            track.thumbnail = best.thumbnail
        return track

    async def refresh_playable_url(self, track: Track) -> str:
        # Les playlists persistantes gardent des métadonnées stables, pas des URLs
        # audio signées. Si la piste n'a encore aucune source, on la résout maintenant.
        if not track.is_playable:
            await self.ensure_playable(track)

        provider = self._provider_by_name(track.playback_provider)
        if provider is None:
            if not track.playable_url:
                raise NoPlayableSource(track.title, [])
            return track.playable_url
        try:
            url = await provider.refresh_playable_url(track)
            provider.mark_available()
            return url
        except ProviderUnavailable as exc:
            provider.mark_unavailable(exc.reason)
            raise

    def _provider_by_name(self, name: str | None) -> MusicProvider | None:
        for provider in (self.direct, self.spotify, self.deezer, self.soundcloud, self.youtube):
            if provider.name == name:
                return provider
        return None
