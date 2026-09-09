"""SoundCloud, via l'extracteur intégré de yt-dlp (pas l'API officielle SoundCloud,
dont l'enregistrement de nouvelles applications est fermé depuis des années). Ne
contourne aucune protection : yt-dlp respecte le réglage "téléchargement autorisé"
de chaque piste défini par son auteur — une piste que SoundCloud lui-même refuse de
diffuser n'est pas non plus diffusée ici, elle est simplement marquée indisponible
et le ProviderManager passe à la source suivante."""
from __future__ import annotations

import asyncio
import re

import yt_dlp

from ..errors import ProviderUnavailable, TrackNotFound
from ..models import Track
from .base import MusicProvider

_URL_RE = re.compile(r"^(https?://)?(www\.|m\.)?(soundcloud\.com|snd\.sc)/", re.IGNORECASE)

_BASE_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "socket_timeout": 15,
}

_NOT_FOUND_MARKERS = ("404", "not found", "unavailable", "no longer available")


def _entry_to_track(entry: dict, *, requested_by: int | None) -> Track:
    return Track(
        title=entry.get("title") or "Titre inconnu",
        artist=entry.get("uploader") or entry.get("artist"),
        duration=int(entry["duration"]) if entry.get("duration") else None,
        thumbnail=entry.get("thumbnail"),
        original_url=entry.get("webpage_url") or entry.get("original_url"),
        provider="soundcloud",
        playable_url=entry.get("url"),
        playback_provider="soundcloud",
        is_live=bool(entry.get("is_live")),
        requested_by=requested_by,
    )


class SoundCloudProvider(MusicProvider):
    name = "soundcloud"
    can_provide_playback = True
    can_search_by_text = True

    def matches(self, query: str) -> bool:
        return bool(_URL_RE.match(query.strip()))

    async def _extract(self, query: str) -> dict:
        loop = asyncio.get_event_loop()

        def _run():
            with yt_dlp.YoutubeDL(_BASE_OPTS) as ydl:
                return ydl.extract_info(query, download=False)

        try:
            return await loop.run_in_executor(None, _run)
        except yt_dlp.utils.DownloadError as exc:
            text = str(exc).casefold()
            if any(marker in text for marker in _NOT_FOUND_MARKERS):
                raise TrackNotFound(self.name, query) from exc
            raise ProviderUnavailable(self.name, str(exc)[:200]) from exc
        except Exception as exc:
            raise ProviderUnavailable(self.name, f"{type(exc).__name__}: {exc}"[:200]) from exc

    async def resolve_metadata(self, query: str, *, requested_by: int | None = None) -> list[Track]:
        info = await self._extract(query)
        entries = info.get("entries") if "entries" in info else [info]
        entries = [e for e in (entries or []) if e]
        if not entries:
            raise TrackNotFound(self.name, query)
        return [_entry_to_track(entry, requested_by=requested_by) for entry in entries]

    async def search_playable(
        self, *, title: str, artist: str | None, duration: int | None, limit: int = 5,
    ) -> list[Track]:
        query_text = f"{artist} {title}" if artist else title
        info = await self._extract(f"scsearch{limit}:{query_text}")
        entries = [e for e in (info.get("entries") or []) if e]
        return [_entry_to_track(entry, requested_by=None) for entry in entries]

    async def refresh_playable_url(self, track: Track) -> str:
        if not track.original_url:
            return await super().refresh_playable_url(track)
        info = await self._extract(track.original_url)
        url = info.get("url")
        if not url:
            raise ProviderUnavailable(self.name, "flux audio absent de la réponse yt-dlp")
        return url
