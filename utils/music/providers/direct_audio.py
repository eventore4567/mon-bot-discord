"""Lien direct vers un fichier/flux audio (ex: .mp3/.ogg/.opus hébergé quelque
part, flux radio). Vérifie l'extension OU le Content-Type réel avant d'accepter —
un lien qui ne pointe pas vers de l'audio n'est pas "autorisé", il est juste
incorrect, et doit être rejeté ici plutôt que de planter plus loin dans FFmpeg."""
from __future__ import annotations

import re
from urllib.parse import urlparse

import aiohttp

from ..errors import ProviderUnavailable, TrackNotFound
from ..models import Track
from .base import MusicProvider

_AUDIO_EXTENSIONS = (".mp3", ".ogg", ".opus", ".wav", ".flac", ".m4a", ".aac", ".webm")
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=8)


class DirectAudioProvider(MusicProvider):
    name = "direct"
    can_provide_playback = True

    def matches(self, query: str) -> bool:
        query = query.strip()
        if not _URL_RE.match(query):
            return False
        path = urlparse(query).path.casefold()
        return path.endswith(_AUDIO_EXTENSIONS)

    async def resolve_metadata(self, query: str, *, requested_by: int | None = None) -> list[Track]:
        query = query.strip()
        content_type = None
        is_live = False
        try:
            async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
                async with session.head(query, allow_redirects=True) as resp:
                    if resp.status == 404:
                        raise TrackNotFound(self.name, query)
                    if resp.status >= 400:
                        raise ProviderUnavailable(self.name, f"HTTP {resp.status}")
                    content_type = resp.headers.get("Content-Type", "")
                    is_live = "icecast" in resp.headers.get("Server", "").casefold() or resp.headers.get("Content-Length") is None
        except aiohttp.ClientError as exc:
            # Certains serveurs de streaming refusent HEAD (405) : on tente quand
            # même la lecture directe plutôt que de rejeter un lien probablement
            # valide sur un simple détail de méthode HTTP.
            if "405" not in str(exc):
                raise ProviderUnavailable(self.name, f"réseau: {exc}") from exc

        if content_type and not content_type.startswith(("audio/", "application/ogg", "video/")):
            raise TrackNotFound(self.name, query)

        filename = urlparse(query).path.rsplit("/", 1)[-1] or "Flux audio"
        return [
            Track(
                title=filename,
                original_url=query,
                provider=self.name,
                playable_url=query,
                playback_provider=self.name,
                is_live=is_live,
                requested_by=requested_by,
            )
        ]
