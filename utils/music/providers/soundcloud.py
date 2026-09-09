"""SoundCloud via l'extracteur intégré de yt-dlp.

Aucune protection n'est contournée. Pour une recherche texte, on récupère d'abord
une liste légère de candidats, puis on résout chaque piste séparément. Une piste DRM
ou non diffusable est simplement ignorée et les candidats suivants sont essayés ;
elle ne met plus tout le provider SoundCloud en cooldown.
"""
from __future__ import annotations

import asyncio
import logging
import re

import yt_dlp

from ..errors import ProviderUnavailable, TrackNotFound
from ..models import Track
from .base import MusicProvider

logger = logging.getLogger("bot.music.provider.soundcloud")

_URL_RE = re.compile(r"^(https?://)?(www\.|m\.)?(soundcloud\.com|snd\.sc)/", re.IGNORECASE)

_BASE_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "socket_timeout": 15,
}

_NOT_FOUND_MARKERS = ("404", "not found", "unavailable", "no longer available")
_DRM_MARKERS = ("drm protected", "drm-protected", "protected by drm")


def _is_drm_reason(reason: str) -> bool:
    text = (reason or "").casefold()
    return any(marker in text for marker in _DRM_MARKERS)


def _candidate_page_url(entry: dict) -> str | None:
    """Retourne uniquement une URL de page HTTP ré-extractable, jamais un flux
    opaque ou un identifiant interne."""
    for key in ("webpage_url", "original_url", "url"):
        value = entry.get(key)
        if isinstance(value, str) and value.startswith(("https://", "http://")):
            return value
    return None


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

    async def _extract(self, query: str, *, opts_override: dict | None = None) -> dict:
        opts = {**_BASE_OPTS, **(opts_override or {})}
        loop = asyncio.get_running_loop()

        def _run():
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(query, download=False)

        try:
            return await loop.run_in_executor(None, _run)
        except yt_dlp.utils.DownloadError as exc:
            text = str(exc).casefold()
            if any(marker in text for marker in _NOT_FOUND_MARKERS):
                raise TrackNotFound(self.name, query) from exc
            # La distinction DRM/provider-wide est faite par search_playable :
            # _extract reste générique pour qu'un lien SoundCloud direct puisse
            # remonter proprement une indisponibilité sans jamais contourner DRM.
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
        """Cherche plusieurs candidats puis résout chacun individuellement.

        Avant ce correctif, yt-dlp résolvait tout ``scsearch5`` en une fois : si le
        premier résultat était DRM, l'exception interrompait la recherche entière et
        SoundCloud était marqué indisponible 120 s. Désormais une piste DRM est un
        échec local au candidat ; les suivantes restent essayées.
        """
        query_text = f"{artist} {title}" if artist else title
        try:
            listing = await self._extract(
                f"scsearch{limit}:{query_text}",
                opts_override={"extract_flat": True, "noplaylist": True},
            )
        except ProviderUnavailable as exc:
            if _is_drm_reason(exc.reason):
                logger.info("SoundCloud search listing DRM ignored -> %s", query_text)
                return []
            raise

        flat_entries = [e for e in (listing.get("entries") or []) if e]
        results: list[Track] = []
        for flat in flat_entries[:limit]:
            candidate_url = _candidate_page_url(flat)
            if not candidate_url:
                continue
            try:
                info = await self._extract(
                    candidate_url,
                    opts_override={"extract_flat": False, "noplaylist": True},
                )
            except TrackNotFound:
                continue
            except ProviderUnavailable as exc:
                if _is_drm_reason(exc.reason):
                    logger.info("SoundCloud DRM candidate skipped -> %s", candidate_url)
                    continue
                # Erreur réseau/rate-limit/provider-wide : celle-ci doit bien mettre
                # SoundCloud en cooldown via gather_candidates().
                raise

            entries = info.get("entries") if "entries" in info else [info]
            for entry in (e for e in (entries or []) if e):
                track = _entry_to_track(entry, requested_by=None)
                if track.playable_url:
                    results.append(track)
                    break

        return results

    async def refresh_playable_url(self, track: Track) -> str:
        if not track.original_url:
            return await super().refresh_playable_url(track)
        info = await self._extract(track.original_url)
        url = info.get("url")
        if not url:
            raise ProviderUnavailable(self.name, "flux audio absent de la réponse yt-dlp")
        return url
