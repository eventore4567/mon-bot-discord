"""Spotify metadata provider for SentriX.

Spotify is metadata-only here: the official API does not expose a full audio stream
for Discord playback. Metadata is matched to an authorized playback provider by the
ProviderManager. Track URLs can fall back to public oEmbed without credentials;
albums/playlists require official Client Credentials so their individual tracks can be
listed when Spotify allows the requested resource.

Since Spotify's February/March 2026 Development Mode changes, playlist item endpoints
use ``/items`` instead of ``/tracks`` and playlist contents are restricted to playlists
owned by, or collaborative with, the authenticated Spotify user. SentriX never attempts
to bypass that restriction: a 403 on playlist contents is surfaced as a precise product
error while ordinary track/album links keep working normally.
"""
from __future__ import annotations

import re
import time

import aiohttp

import config
from ..errors import ProviderUnavailable, TrackNotFound
from ..models import Track
from .base import MusicProvider

_URL_RE = re.compile(
    r"^(https?://)?open\.spotify\.com/(intl-[a-z]{2}/)?(track|album|playlist)/([A-Za-z0-9]+)",
    re.IGNORECASE,
)
_URI_RE = re.compile(r"^spotify:(track|album|playlist):([A-Za-z0-9]+)$", re.IGNORECASE)

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=12)
_MAX_METADATA_TRACKS = 100
_MAX_PAGES = 10
_SPOTIFY_2026_PLAYLIST_RESTRICTION = (
    "playlist-spotify-2026: Spotify limite le contenu des playlists aux playlists "
    "possedees ou collaboratives du compte authentifie"
)


def _parse_id(query: str) -> tuple[str, str] | None:
    """Return (kind, id), where kind is track/album/playlist."""
    match = _URL_RE.match(query.strip())
    if match:
        return match.group(3).lower(), match.group(4)
    match = _URI_RE.match(query.strip())
    if match:
        return match.group(1).lower(), match.group(2)
    return None


class SpotifyProvider(MusicProvider):
    name = "spotify"
    can_provide_playback = False

    def __init__(self):
        super().__init__()
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def matches(self, query: str) -> bool:
        return _parse_id(query) is not None

    @property
    def _has_credentials(self) -> bool:
        return bool(config.SPOTIFY_CLIENT_ID and config.SPOTIFY_CLIENT_SECRET)

    async def _get_token(self, session: aiohttp.ClientSession) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        try:
            async with session.post(
                "https://accounts.spotify.com/api/token",
                data={"grant_type": "client_credentials"},
                auth=aiohttp.BasicAuth(config.SPOTIFY_CLIENT_ID, config.SPOTIFY_CLIENT_SECRET),
            ) as resp:
                if resp.status != 200:
                    raise ProviderUnavailable(self.name, f"auth HTTP {resp.status}")
                payload = await resp.json()
        except aiohttp.ClientError as exc:
            raise ProviderUnavailable(self.name, f"auth reseau: {exc}") from exc
        token = payload.get("access_token")
        if not token:
            raise ProviderUnavailable(self.name, "auth sans access_token")
        self._token = str(token)
        self._token_expires_at = time.monotonic() + int(payload.get("expires_in", 3600)) - 30
        return self._token

    async def _api_get(
        self,
        session: aiohttp.ClientSession,
        url: str,
        headers: dict[str, str],
        *,
        not_found_query: str,
        forbidden_reason: str | None = None,
    ) -> dict:
        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 404:
                    raise TrackNotFound(self.name, not_found_query)
                if resp.status == 403 and forbidden_reason:
                    raise ProviderUnavailable(self.name, forbidden_reason)
                if resp.status in (401, 403, 429) or resp.status >= 500:
                    raise ProviderUnavailable(self.name, f"API HTTP {resp.status}")
                if resp.status != 200:
                    raise ProviderUnavailable(self.name, f"API HTTP {resp.status}")
                return await resp.json()
        except aiohttp.ClientError as exc:
            raise ProviderUnavailable(self.name, f"reseau: {exc}") from exc

    async def _resolve_via_api(
        self,
        kind: str,
        spotify_id: str,
        *,
        requested_by: int | None,
    ) -> list[Track]:
        async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
            token = await self._get_token(session)
            headers = {"Authorization": f"Bearer {token}"}

            if kind == "track":
                data = await self._api_get(
                    session,
                    f"https://api.spotify.com/v1/tracks/{spotify_id}",
                    headers,
                    not_found_query=spotify_id,
                )
                return [self._track_from_api(data, requested_by=requested_by)]

            forbidden_reason = None
            if kind == "album":
                next_url: str | None = f"https://api.spotify.com/v1/albums/{spotify_id}/tracks?limit=50"
            else:
                # Spotify 2026: /playlists/{id}/tracks a ete remplace par /items.
                next_url = f"https://api.spotify.com/v1/playlists/{spotify_id}/items?limit=100"
                forbidden_reason = _SPOTIFY_2026_PLAYLIST_RESTRICTION

            tracks: list[Track] = []
            pages = 0
            while next_url and len(tracks) < _MAX_METADATA_TRACKS and pages < _MAX_PAGES:
                pages += 1
                data = await self._api_get(
                    session,
                    next_url,
                    headers,
                    not_found_query=spotify_id,
                    forbidden_reason=forbidden_reason,
                )
                for item in data.get("items", []) or []:
                    if kind == "playlist":
                        # Development Mode 2026 renomme item.track -> item.item. Garder le
                        # fallback historique rend aussi SentriX compatible Extended Quota.
                        payload = item.get("item") or item.get("track") or item
                    else:
                        payload = item
                    if not isinstance(payload, dict) or not payload.get("name"):
                        continue
                    tracks.append(self._track_from_api(payload, requested_by=requested_by))
                    if len(tracks) >= _MAX_METADATA_TRACKS:
                        break
                raw_next = data.get("next")
                next_url = str(raw_next) if raw_next else None

        if not tracks:
            raise TrackNotFound(self.name, spotify_id)
        return tracks

    def _track_from_api(self, data: dict, *, requested_by: int | None) -> Track:
        artists = ", ".join(a["name"] for a in data.get("artists", []) if a.get("name"))
        album = data.get("album") or {}
        images = album.get("images") or []
        return Track(
            title=data.get("name") or "Titre inconnu",
            artist=artists or None,
            album=album.get("name"),
            duration=(data.get("duration_ms") or 0) // 1000 or None,
            thumbnail=images[0]["url"] if images else None,
            original_url=(data.get("external_urls") or {}).get("spotify"),
            provider=self.name,
            requested_by=requested_by,
        )

    async def _resolve_via_oembed(self, query: str, *, requested_by: int | None) -> list[Track]:
        try:
            async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
                async with session.get(
                    "https://open.spotify.com/oembed", params={"url": query}
                ) as resp:
                    if resp.status == 404:
                        raise TrackNotFound(self.name, query)
                    if resp.status != 200:
                        raise ProviderUnavailable(self.name, f"oEmbed HTTP {resp.status}")
                    data = await resp.json()
        except aiohttp.ClientError as exc:
            raise ProviderUnavailable(self.name, f"oEmbed reseau: {exc}") from exc

        title = data.get("title") or "Titre inconnu"
        artist = None
        for sep in (" par ", " by ", " · "):
            if sep in title:
                title, artist = title.split(sep, 1)
                break
        return [
            Track(
                title=title.strip(),
                artist=artist.strip() if artist else None,
                thumbnail=data.get("thumbnail_url"),
                original_url=query,
                provider=self.name,
                requested_by=requested_by,
            )
        ]

    async def resolve_metadata(self, query: str, *, requested_by: int | None = None) -> list[Track]:
        parsed = _parse_id(query)
        if parsed is None:
            raise TrackNotFound(self.name, query)
        kind, spotify_id = parsed
        if self._has_credentials:
            return await self._resolve_via_api(kind, spotify_id, requested_by=requested_by)
        if kind != "track":
            raise ProviderUnavailable(
                self.name,
                "SPOTIFY_CLIENT_ID/SPOTIFY_CLIENT_SECRET requis pour importer un album ou une playlist Spotify",
            )
        return await self._resolve_via_oembed(query, requested_by=requested_by)
