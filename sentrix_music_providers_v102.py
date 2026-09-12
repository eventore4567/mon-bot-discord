"""SentriX V102 — passerelle musique multi-fournisseurs + transport audio stable.

Objectif utilisateur : ``/music play`` et ``+play`` acceptent un titre, un lien
YouTube/YouTube Music, un lien Spotify ou un lien Deezer.

Spotify et Deezer ne fournissent pas un flux audio Discord librement lisible : leurs
pages sont protégées/DRM. On résout donc proprement le titre via leurs métadonnées
publiques puis on recherche la piste équivalente sur YouTube. Aucune tentative de
contournement DRM n'est faite.

Le correctif est installé très tôt depuis le véritable bootstrap Railway et enveloppe
``Bot.add_cog`` plutôt que d'ajouter une nouvelle commande. La même couche applique aussi
les réglages FFmpeg anti-jitter au Cog Music moderne : reconnexion réseau plus tolérante,
normalisation 48 kHz stéréo et resampling asynchrone pour absorber les micro-coupures de
flux sans désactiver le contrôle de volume PCM.

V104 branche en plus la persistance vocale : une connexion créée par Music reste dans
le salon jusqu'à ``/music leave`` et est restaurée après restart/failover.

V108 ajoute enfin les playlists personnelles persistantes sous ``/music playlist`` et
un ping au demandeur lorsque la file musicale est réellement terminée.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import types
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from discord.ext import commands

logger = logging.getLogger("bot.music-v102")

_INSTALLED = False
_ORIGINAL_ADD_COG = None

# Les flux distants (notamment les fallbacks SoundCloud) peuvent présenter de très petits
# trous réseau ou des timestamps légèrement irréguliers. Discord attend du PCM 48 kHz à
# cadence régulière. Ces options laissent FFmpeg reconnecter proprement et ``aresample``
# compense les petits écarts de timestamps au lieu de transmettre une micro-coupure audible.
# On évite volontairement ``-fflags nobuffer`` : il diminuerait la marge anti-jitter.
_SMOOTH_FFMPEG_OPTIONS = {
    "before_options": (
        "-reconnect 1 -reconnect_streamed 1 -reconnect_at_eof 1 "
        "-reconnect_delay_max 10 -rw_timeout 15000000"
    ),
    "options": "-vn -ar 48000 -ac 2 -af aresample=48000:async=1000:first_pts=0",
}

_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}
_SPOTIFY_HOSTS = {"open.spotify.com", "spotify.link", "www.spotify.com"}
_DEEZER_HOSTS = {
    "deezer.com",
    "www.deezer.com",
    "link.deezer.com",
    "deezer.page.link",
}


def _clean_query(value: str) -> str:
    value = str(value or "").strip()
    if len(value) >= 2 and value.startswith("<") and value.endswith(">"):
        value = value[1:-1].strip()
    return value


def _host(value: str) -> str:
    try:
        return (urlparse(value).hostname or "").casefold()
    except Exception:
        return ""


def _host_matches(host: str, allowed: set[str]) -> bool:
    return host in allowed or any(host.endswith("." + item) for item in allowed if "." in item)


def _is_youtube(value: str) -> bool:
    return _host_matches(_host(value), _YOUTUBE_HOSTS)


def _is_spotify(value: str) -> bool:
    return _host_matches(_host(value), _SPOTIFY_HOSTS)


def _is_deezer(value: str) -> bool:
    return _host_matches(_host(value), _DEEZER_HOSTS)


def _request_json(url: str, *, timeout: float = 12.0) -> tuple[dict, str]:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; SentriXMusic/102)",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URLs are fixed/provider URLs
        payload = response.read(1_500_000)
        final_url = response.geturl()
    return json.loads(payload.decode("utf-8", errors="replace")), final_url


def _resolve_redirect(url: str, *, timeout: float = 12.0) -> str:
    request = Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; SentriXMusic/102)"},
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - user URL is restricted by host before call
        return response.geturl()


def _spotify_metadata(url: str) -> dict:
    endpoint = "https://open.spotify.com/oembed?" + urlencode({"url": url})
    data, _ = _request_json(endpoint)
    title = str(data.get("title") or "").strip()
    if not title:
        raise ValueError("Spotify n'a pas renvoyé le titre de cette piste")
    return {
        "provider": "Spotify",
        "search": f"{title} official audio",
        "provider_title": title,
        "provider_url": url,
        "provider_thumbnail": str(data.get("thumbnail_url") or ""),
    }


def _deezer_metadata(url: str) -> dict:
    final_url = _resolve_redirect(url) if _host(url) in {"link.deezer.com", "deezer.page.link"} else url
    match = re.search(r"/(?:[a-z]{2}/)?track/(\d+)(?:[/?#]|$)", urlparse(final_url).path + "/")
    if not match:
        # Certains liens de partage gardent l'identifiant dans l'URL finale complète.
        match = re.search(r"/track/(\d+)", final_url)
    if not match:
        raise ValueError("Ce lien Deezer n'est pas un lien de piste reconnu")

    track_id = match.group(1)
    data, _ = _request_json(f"https://api.deezer.com/track/{track_id}")
    if data.get("error"):
        raise ValueError("Deezer n'a pas renvoyé cette piste")
    title = str(data.get("title") or "").strip()
    artist = str((data.get("artist") or {}).get("name") or "").strip()
    if not title:
        raise ValueError("Deezer n'a pas renvoyé le titre de cette piste")
    search = " - ".join(part for part in (artist, title) if part)
    if search:
        search += " official audio"
    return {
        "provider": "Deezer",
        "search": search or f"{title} official audio",
        "provider_title": " - ".join(part for part in (artist, title) if part) or title,
        "provider_url": final_url,
        "provider_thumbnail": str((data.get("album") or {}).get("cover_xl") or ""),
    }


async def _provider_metadata(query: str) -> dict | None:
    try:
        if _is_spotify(query):
            return await asyncio.to_thread(_spotify_metadata, query)
        if _is_deezer(query):
            return await asyncio.to_thread(_deezer_metadata, query)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Résolution du lien musique impossible provider=%s erreur=%s", _host(query), exc)
        raise
    return None


def _youtube_options(base: dict, player_clients: list[str] | None = None) -> dict:
    options = dict(base)
    # Le binaire Deno est copié explicitement dans l'image Railway. Le chemin évite qu'un
    # PATH réduit au démarrage fasse croire à yt-dlp qu'aucun runtime JS n'est présent.
    options["js_runtimes"] = {"deno": {"path": "/usr/local/bin/deno"}}
    options["noplaylist"] = True
    options["quiet"] = True
    options["socket_timeout"] = 20
    options["retries"] = 3
    options["extractor_retries"] = 3
    options["fragment_retries"] = 3
    if player_clients:
        options["extractor_args"] = {
            "youtube": {
                "player_client": player_clients,
            }
        }
    return options


def _first_entry(info: dict | None) -> dict:
    if not info:
        raise ValueError("aucun résultat")
    if "entries" in info:
        entries = [entry for entry in (info.get("entries") or []) if entry]
        if not entries:
            raise ValueError("aucun résultat exploitable")
        info = entries[0]
    if not isinstance(info, dict):
        raise ValueError("résultat musique invalide")
    return info


def _retryable_youtube_error(exc: Exception) -> bool:
    message = str(exc).casefold()
    return any(
        marker in message
        for marker in (
            "sign in to confirm",
            "not a bot",
            "login_required",
            "po token",
            "http error 403",
            "forbidden",
            "no supported javascript runtime",
            "player response",
            "requested format is not available",
        )
    )


async def _patched_ytdl_extract(self, query: str) -> dict:
    """Résout YouTube/Spotify/Deezer puis obtient un flux audio jouable."""
    import yt_dlp

    original_query = _clean_query(query)
    if not original_query:
        raise ValueError("recherche vide")

    provider = await _provider_metadata(original_query)
    if provider:
        target = "ytsearch1:" + provider["search"]
    elif _is_youtube(original_query) or "://" in original_query:
        target = original_query
    else:
        # Préfixe explicite : on maîtrise le moteur de recherche au lieu de dépendre de
        # ``default_search`` et les retries utilisent exactement le même chemin.
        target = "ytsearch1:" + original_query

    base = getattr(__import__("cogs.music", fromlist=["YTDL_OPTIONS"]), "YTDL_OPTIONS", {})
    attempts = [
        _youtube_options(base),
        _youtube_options(base, ["web_embedded", "android_vr"]),
        _youtube_options(base, ["web_safari", "android_vr"]),
    ]

    last_error: Exception | None = None
    for index, options in enumerate(attempts, 1):
        try:
            info = _first_entry(await self._extract_info(target, options))
            stream_url = info.get("url")
            if not stream_url:
                raise ValueError("aucun flux audio disponible")

            result = {
                "title": info.get("title", provider["provider_title"] if provider else "Titre inconnu"),
                "url": stream_url,
                "webpage_url": info.get("webpage_url", provider["provider_url"] if provider else ""),
                "thumbnail": info.get("thumbnail", provider["provider_thumbnail"] if provider else ""),
                "duration": info.get("duration", 0),
                "uploader": info.get("uploader", ""),
            }
            if provider:
                result["requested_provider"] = provider["provider"]
                result["requested_url"] = provider["provider_url"]
            if index > 1:
                logger.info("Musique V102 extraite via fallback YouTube %s/3.", index)
            return result
        except yt_dlp.utils.DownloadError as exc:
            last_error = exc
            if index == len(attempts) or not _retryable_youtube_error(exc):
                break
        except ValueError as exc:
            last_error = exc
            if index == len(attempts):
                break

    if last_error is not None:
        raise last_error
    raise ValueError("aucun flux audio disponible")


def _install_smooth_ffmpeg_defaults(cog) -> None:
    """Applique les réglages audio au Cog moderne sans remplacer sa logique métier."""
    if getattr(cog, "_sentrix_music_audio_v103", False):
        return
    try:
        music_module = __import__(cog.__class__.__module__, fromlist=["FFMPEG_OPTIONS"])
        current = getattr(music_module, "FFMPEG_OPTIONS", {})
        options = dict(current) if isinstance(current, dict) else {}
        options.update(_SMOOTH_FFMPEG_OPTIONS)
        music_module.FFMPEG_OPTIONS = options
        cog._sentrix_music_audio_v103 = True
        logger.warning(
            "Musique V103 audio fluide active : reconnexion renforcée + PCM 48 kHz stéréo + anti-jitter aresample."
        )
    except Exception:
        logger.exception("Installation des réglages audio V103 impossible.")


def _install_persistent_voice(bot, cog) -> None:
    """Branche V104 sans dupliquer les commandes Music ni leur logique métier."""
    try:
        from sentrix_music_voice_persistence import install_on_cog

        install_on_cog(bot, cog)
    except Exception:
        logger.exception("Installation de la persistance vocale V104 impossible.")


def _patch_music_cog(bot, cog) -> None:
    # Cette partie s'applique aussi au nouveau moteur utils/music/, qui n'expose plus
    # _extract_info/ytdl_extract mais utilise toujours le FFMPEG_OPTIONS de cogs.music.
    _install_smooth_ffmpeg_defaults(cog)
    _install_persistent_voice(bot, cog)

    # Compatibilité avec l'ancien moteur V102 encore présent dans certaines branches.
    if getattr(cog, "_sentrix_music_v102", False):
        return
    if not hasattr(cog, "_extract_info") or not hasattr(cog, "ytdl_extract"):
        return
    cog.ytdl_extract = types.MethodType(_patched_ytdl_extract, cog)
    cog._sentrix_music_v102 = True
    logger.warning(
        "Musique V102 active : entrées YouTube/YouTube Music + Spotify + Deezer, "
        "résolution Spotify/Deezer vers une piste audio YouTube équivalente."
    )


def install() -> None:
    """Patche l'ajout du Cog Music sans créer de commande supplémentaire."""
    global _INSTALLED, _ORIGINAL_ADD_COG
    if _INSTALLED:
        return

    original = commands.Bot.add_cog
    if getattr(original, "_sentrix_music_v102_loader", False):
        _INSTALLED = True
        return
    _ORIGINAL_ADD_COG = original

    async def add_cog_with_music_v102(bot, cog, *args, **kwargs):
        result = await original(bot, cog, *args, **kwargs)
        if cog.__class__.__name__ == "Music" or getattr(cog, "qualified_name", None) == "Music":
            _patch_music_cog(bot, cog)
            try:
                from sentrix_music_playlists_v108 import install_on_music_cog

                await install_on_music_cog(bot, cog)
            except Exception:
                logger.exception("Installation de la musique V108 impossible.")
        return result

    add_cog_with_music_v102._sentrix_music_v102_loader = True
    add_cog_with_music_v102.__wrapped__ = original
    commands.Bot.add_cog = add_cog_with_music_v102
    _INSTALLED = True
    logger.info("Chargeur musique V102/V103/V104/V108 préparé avant le chargement des Cogs.")


__all__ = ["install"]