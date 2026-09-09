"""YouTube + YouTube Music. music.youtube.com sert le même catalogue que
youtube.com via la même API interne : yt-dlp les traite de façon identique, donc un
seul provider couvre les deux plutôt que de dupliquer l'extraction (voir le
docstring du module utils/music/providers/__init__.py)."""
from __future__ import annotations

import asyncio
import logging
import re

import yt_dlp

from ..errors import ProviderUnavailable, TrackNotFound
from ..models import Track
from .base import MusicProvider

logger = logging.getLogger("bot.music.provider.youtube")

_URL_RE = re.compile(
    r"^(https?://)?(www\.|music\.|m\.)?(youtube\.com|youtu\.be)/", re.IGNORECASE
)
_PLAYLIST_HINT_RE = re.compile(r"[?&]list=", re.IGNORECASE)

# Signatures connues d'un blocage anti-bot / rate-limit YouTube — PAS "cette vidéo
# n'existe pas". C'est précisément ce qui bloque Railway (IP de datacenter connue) :
# voir la demande explicite de ne jamais laisser ça faire tomber toute la commande.
_ANTI_BOT_MARKERS = (
    "sign in to confirm",
    "confirm you're not a bot",
    "429",
    "too many requests",
    "http error 403",
    "unable to download webpage",
)
# Signatures d'un vrai "ce contenu n'existe plus" — celles-là ne doivent PAS
# déclencher de cooldown provider, juste "morceau introuvable".
_NOT_FOUND_MARKERS = (
    "video unavailable",
    "private video",
    "this video is unavailable",
    "has been removed",
    "does not exist",
)

_BASE_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "extract_flat": False,
    "source_address": "0.0.0.0",
    "socket_timeout": 15,
}


def _classify_error(exc: Exception) -> str:
    text = str(exc).casefold()
    if any(marker in text for marker in _NOT_FOUND_MARKERS):
        return "not_found"
    if any(marker in text for marker in _ANTI_BOT_MARKERS):
        return "blocked"
    return "blocked"  # par prudence : une erreur inconnue de yt-dlp est traitée comme un blocage temporaire, pas comme "n'existe pas"


def _entry_to_track(entry: dict, *, requested_by: int | None) -> Track:
    return Track(
        title=entry.get("title") or "Titre inconnu",
        artist=entry.get("artist") or entry.get("uploader") or entry.get("channel"),
        album=entry.get("album"),
        duration=int(entry["duration"]) if entry.get("duration") else None,
        thumbnail=entry.get("thumbnail"),
        original_url=entry.get("webpage_url") or entry.get("original_url"),
        provider="youtube",
        playable_url=entry.get("url"),
        playback_provider="youtube",
        is_live=bool(entry.get("is_live")),
        requested_by=requested_by,
    )


class YouTubeProvider(MusicProvider):
    name = "youtube"
    can_provide_playback = True
    can_search_by_text = True

    def matches(self, query: str) -> bool:
        return bool(_URL_RE.match(query.strip()))

    async def _extract(self, query: str, *, opts_override: dict | None = None) -> dict:
        opts = {**_BASE_OPTS, **(opts_override or {})}
        loop = asyncio.get_event_loop()

        def _run():
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(query, download=False)

        try:
            return await loop.run_in_executor(None, _run)
        except yt_dlp.utils.DownloadError as exc:
            kind = _classify_error(exc)
            if kind == "not_found":
                raise TrackNotFound(self.name, query) from exc
            raise ProviderUnavailable(self.name, str(exc)[:200]) from exc
        except Exception as exc:  # réseau, timeout, etc. -> jamais un crash de commande
            raise ProviderUnavailable(self.name, f"{type(exc).__name__}: {exc}"[:200]) from exc

    async def resolve_metadata(self, query: str, *, requested_by: int | None = None) -> list[Track]:
        is_playlist = bool(_PLAYLIST_HINT_RE.search(query)) and "watch?v=" not in query
        opts = {"noplaylist": not is_playlist}
        info = await self._extract(query, opts_override=opts)
        entries = info.get("entries") if "entries" in info else [info]
        entries = [e for e in (entries or []) if e]
        if not entries:
            raise TrackNotFound(self.name, query)
        return [_entry_to_track(entry, requested_by=requested_by) for entry in entries]

    async def search_playable(
        self, *, title: str, artist: str | None, duration: int | None, limit: int = 5,
    ) -> list[Track]:
        query_text = f"{artist} {title}" if artist else title
        info = await self._extract(
            f"ytsearch{limit}:{query_text}",
            opts_override={"noplaylist": True},
        )
        entries = [e for e in (info.get("entries") or []) if e]
        return [_entry_to_track(entry, requested_by=None) for entry in entries]

    async def refresh_playable_url(self, track: Track) -> str:
        if not track.original_url:
            return await super().refresh_playable_url(track)
        info = await self._extract(track.original_url, opts_override={"noplaylist": True})
        url = info.get("url")
        if not url:
            raise ProviderUnavailable(self.name, "flux audio absent de la réponse yt-dlp")
        return url
