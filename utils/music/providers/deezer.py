"""Deezer — MÉTADONNÉES UNIQUEMENT, via l'API publique (https://api.deezer.com,
aucune clé requise). Deezer expose bien un champ `preview` (extrait de 30 secondes)
mais ce n'est pas le morceau complet : le faire passer pour une lecture normale
serait trompeur, donc can_provide_playback reste False et le ProviderManager
cherche la version complète ailleurs via matcher.py — exactement le même principe
que Spotify (voir spotify.py)."""
from __future__ import annotations

import re

import aiohttp

from ..errors import ProviderUnavailable, TrackNotFound
from ..models import Track
from .base import MusicProvider

_URL_RE = re.compile(
    r"^(https?://)?(www\.)?deezer\.com/(?:[a-z]{2}/)?(track|album|playlist)/(\d+)",
    re.IGNORECASE,
)
_SHORT_URL_RE = re.compile(r"^(https?://)?(link|deezer)\.deezer\.com/", re.IGNORECASE)

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)


class DeezerProvider(MusicProvider):
    name = "deezer"
    can_provide_playback = False

    def matches(self, query: str) -> bool:
        query = query.strip()
        return bool(_URL_RE.match(query) or _SHORT_URL_RE.match(query))

    async def _resolve_short_url(self, session: aiohttp.ClientSession, query: str) -> str:
        """link.deezer.com renvoie un lien court (ex: partage mobile) qui redirige
        vers la vraie URL deezer.com/track/... — on suit juste la redirection, on
        ne devine rien."""
        try:
            async with session.get(query, allow_redirects=True) as resp:
                return str(resp.url)
        except aiohttp.ClientError as exc:
            raise ProviderUnavailable(self.name, f"résolution lien court: {exc}") from exc

    async def resolve_metadata(self, query: str, *, requested_by: int | None = None) -> list[Track]:
        query = query.strip()
        async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
            if _SHORT_URL_RE.match(query):
                query = await self._resolve_short_url(session, query)

            match = _URL_RE.match(query)
            if not match:
                raise TrackNotFound(self.name, query)
            kind, deezer_id = match.group(3).lower(), match.group(4)

            try:
                async with session.get(f"https://api.deezer.com/{kind}/{deezer_id}") as resp:
                    if resp.status != 200:
                        raise ProviderUnavailable(self.name, f"API HTTP {resp.status}")
                    data = await resp.json()
            except aiohttp.ClientError as exc:
                raise ProviderUnavailable(self.name, f"réseau: {exc}") from exc

        if data.get("error"):
            error = data["error"]
            if error.get("type") in ("DataException",) or "no data" in str(error.get("message", "")).casefold():
                raise TrackNotFound(self.name, query)
            raise ProviderUnavailable(self.name, str(error.get("message", error)))

        if kind == "track":
            return [self._track_from_api(data, requested_by=requested_by)]

        tracks_data = data.get("tracks", {}).get("data", [])
        if not tracks_data:
            raise TrackNotFound(self.name, query)
        return [self._track_from_api(item, requested_by=requested_by) for item in tracks_data]

    def _track_from_api(self, data: dict, *, requested_by: int | None) -> Track:
        artist = (data.get("artist") or {}).get("name")
        album = (data.get("album") or {}).get("title")
        thumbnail = (data.get("album") or {}).get("cover_medium") or data.get("album", {}).get("cover")
        return Track(
            title=data.get("title") or data.get("title_short") or "Titre inconnu",
            artist=artist,
            album=album,
            duration=data.get("duration") or None,
            thumbnail=thumbnail,
            original_url=data.get("link"),
            provider=self.name,
            requested_by=requested_by,
        )
