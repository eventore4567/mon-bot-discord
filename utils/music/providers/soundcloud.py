"""SoundCloud via l'extracteur intégré de yt-dlp.

Aucune protection n'est contournée. Pour une recherche texte, on récupère d'abord
une liste légère de candidats, puis on résout chaque piste séparément. Une piste DRM
ou non diffusable est simplement ignorée et les candidats suivants sont essayés ;
elle ne met plus tout le provider SoundCloud en cooldown.

Pour la lecture Discord on préfère, lorsqu'il existe, un flux audio HTTP progressif
plutôt qu'un manifeste HLS segmenté. Sur une VM Railway cela réduit les micro-coupures
liées au renouvellement de petits segments réseau, tout en gardant le meilleur débit
disponible parmi les formats progressifs. HLS reste le fallback si c'est la seule source.
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
    "retries": 3,
    "extractor_retries": 3,
    "fragment_retries": 5,
}

_NOT_FOUND_MARKERS = ("404", "not found", "unavailable", "no longer available")
_DRM_MARKERS = ("drm protected", "drm-protected", "protected by drm")
_HLS_PROTOCOL_MARKERS = ("m3u8", "hls")
# On garde 5 résultats utiles maximum, mais on regarde plus loin dans la liste quand
# les premiers résultats sont DRM/non diffusables. Cela évite qu'un seul upload
# protégé fasse échouer un +play alors qu'un miroir lisible existe juste après.
_SEARCH_FALLBACK_LIMIT = 12


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


def _format_bitrate(fmt: dict) -> float:
    """Score qualité tolérant aux métadonnées yt-dlp incomplètes."""
    for key in ("abr", "tbr"):
        try:
            value = float(fmt.get(key) or 0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
    return 0.0


def _is_progressive_audio(fmt: dict) -> bool:
    url = str(fmt.get("url") or "").casefold()
    protocol = str(fmt.get("protocol") or "").casefold()
    if not url.startswith(("https://", "http://")):
        return False
    if url.endswith(".m3u8") or ".m3u8?" in url:
        return False
    if any(marker in protocol for marker in _HLS_PROTOCOL_MARKERS):
        return False
    # Un format avec vidéo n'est pas utile au bot et consommerait inutilement bande passante/CPU.
    vcodec = str(fmt.get("vcodec") or "none").casefold()
    return vcodec in {"none", "", "null"}


def _select_playable_url(entry: dict) -> str | None:
    """Choisit le flux le plus stable pour Discord.

    1. audio HTTP progressif, trié par débit ;
    2. meilleur format audio restant (souvent HLS) ;
    3. URL déjà choisie par yt-dlp pour compatibilité.
    """
    formats = [fmt for fmt in (entry.get("formats") or []) if isinstance(fmt, dict) and fmt.get("url")]
    progressive = [fmt for fmt in formats if _is_progressive_audio(fmt)]
    if progressive:
        best = max(progressive, key=_format_bitrate)
        return str(best.get("url"))

    audio_formats = []
    for fmt in formats:
        vcodec = str(fmt.get("vcodec") or "none").casefold()
        if vcodec in {"none", "", "null"}:
            audio_formats.append(fmt)
    if audio_formats:
        best = max(audio_formats, key=_format_bitrate)
        return str(best.get("url"))

    url = entry.get("url")
    return str(url) if isinstance(url, str) and url else None


def _entry_to_track(entry: dict, *, requested_by: int | None) -> Track:
    return Track(
        title=entry.get("title") or "Titre inconnu",
        artist=entry.get("uploader") or entry.get("artist"),
        duration=int(entry["duration"]) if entry.get("duration") else None,
        thumbnail=entry.get("thumbnail"),
        original_url=entry.get("webpage_url") or entry.get("original_url"),
        provider="soundcloud",
        playable_url=_select_playable_url(entry),
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

        Le listing regarde jusqu'à ``_SEARCH_FALLBACK_LIMIT`` résultats quand les
        premiers sont DRM/non diffusables, tout en ne renvoyant jamais plus de
        ``limit`` pistes utiles au moteur de matching.
        """
        query_text = f"{artist} {title}" if artist else title
        listing_limit = max(limit, _SEARCH_FALLBACK_LIMIT)
        try:
            listing = await self._extract(
                f"scsearch{listing_limit}:{query_text}",
                opts_override={"extract_flat": True, "noplaylist": True},
            )
        except ProviderUnavailable as exc:
            if _is_drm_reason(exc.reason):
                logger.info("SoundCloud search listing DRM ignored -> %s", query_text)
                return []
            raise

        flat_entries = [e for e in (listing.get("entries") or []) if e]
        results: list[Track] = []
        for flat in flat_entries[:listing_limit]:
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
            if len(results) >= limit:
                break

        return results

    async def refresh_playable_url(self, track: Track) -> str:
        if not track.original_url:
            return await super().refresh_playable_url(track)
        info = await self._extract(track.original_url)
        entry = info
        if "entries" in info:
            entries = [candidate for candidate in (info.get("entries") or []) if candidate]
            if not entries:
                raise ProviderUnavailable(self.name, "flux audio absent de la réponse yt-dlp")
            entry = entries[0]
        url = _select_playable_url(entry)
        if not url:
            raise ProviderUnavailable(self.name, "flux audio absent de la réponse yt-dlp")
        return url
