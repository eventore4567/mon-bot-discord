"""Spotify — MÉTADONNÉES UNIQUEMENT (titre/artiste/album/durée). L'API Spotify ne
fournit jamais de flux audio exploitable à une application tierce (Client
Credentials Flow, sans utilisateur) : ce n'est ni un oubli ni une limitation
technique de SentriX à contourner, c'est une restriction contractuelle délibérée de
Spotify. can_provide_playback reste donc False — le ProviderManager cherche
toujours la lecture ailleurs via matcher.py, jamais en retombant "juste sur
YouTube" sans passer par le matching intelligent (c'est exactement l'ancien
comportement que cette refonte remplace).

Avec SPOTIFY_CLIENT_ID/SPOTIFY_CLIENT_SECRET configurées : Client Credentials Flow
officiel (titre, artiste(s), album, durée précise en ms). Sans ces variables :
endpoint public oEmbed (https://open.spotify.com/oembed), qui ne demande aucune
clé mais ne renvoie qu'un titre combiné (souvent "Titre" ou "Titre - Artiste" selon
le type de contenu) — moins précis pour le matching mais fonctionnel dès
l'installation, sans configuration."""
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

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)


def _parse_id(query: str) -> tuple[str, str] | None:
    """Retourne (type, id) ou None. type ∈ {"track", "album", "playlist"}."""
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
            raise ProviderUnavailable(self.name, f"auth réseau: {exc}") from exc
        self._token = payload["access_token"]
        self._token_expires_at = time.monotonic() + int(payload.get("expires_in", 3600)) - 30
        return self._token

    async def _resolve_via_api(self, kind: str, spotify_id: str, *, requested_by: int | None) -> list[Track]:
        async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
            token = await self._get_token(session)
            headers = {"Authorization": f"Bearer {token}"}
            if kind == "track":
                url = f"https://api.spotify.com/v1/tracks/{spotify_id}"
            elif kind == "album":
                url = f"https://api.spotify.com/v1/albums/{spotify_id}/tracks?limit=50"
            else:
                url = f"https://api.spotify.com/v1/playlists/{spotify_id}/tracks?limit=100"
            try:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 404:
                        raise TrackNotFound(self.name, spotify_id)
                    if resp.status in (401, 403, 429) or resp.status >= 500:
                        raise ProviderUnavailable(self.name, f"API HTTP {resp.status}")
                    if resp.status != 200:
                        raise ProviderUnavailable(self.name, f"API HTTP {resp.status}")
                    data = await resp.json()
            except aiohttp.ClientError as exc:
                raise ProviderUnavailable(self.name, f"réseau: {exc}") from exc

        if kind == "track":
            return [self._track_from_api(data, requested_by=requested_by)]

        items = data.get("items", [])
        tracks = []
        for item in items:
            payload = item.get("track", item) if kind == "playlist" else item
            if not payload:
                continue
            tracks.append(self._track_from_api(payload, requested_by=requested_by))
        if not tracks:
            raise TrackNotFound(self.name, spotify_id)
        return tracks

    def _track_from_api(self, data: dict, *, requested_by: int | None) -> Track:
        artists = ", ".join(a["name"] for a in data.get("artists", []) if a.get("name"))
        images = (data.get("album") or {}).get("images") or []
        return Track(
            title=data.get("name") or "Titre inconnu",
            artist=artists or None,
            album=(data.get("album") or {}).get("name"),
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
            raise ProviderUnavailable(self.name, f"oEmbed réseau: {exc}") from exc

        title = data.get("title") or "Titre inconnu"
        # L'oEmbed Spotify renvoie parfois "Titre" seul, parfois "Titre par Artiste"
        # selon le type de page — on tente une extraction sans jamais planter si le
        # format diffère.
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
            # oEmbed ne décrit qu'une page, jamais le contenu d'une playlist/album —
            # sans clé API on ne peut pas lister les pistes individuellement.
            raise ProviderUnavailable(
                self.name,
                "SPOTIFY_CLIENT_ID/SPOTIFY_CLIENT_SECRET requis pour résoudre un album/playlist Spotify",
            )
        return await self._resolve_via_oembed(query, requested_by=requested_by)
