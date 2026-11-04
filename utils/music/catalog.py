"""Identifier le morceau demandé avant de chercher où le jouer (04/11/2026).

Jayden : « pour chercher une musique il utilise une clé API, donc si ce n'est pas le
bon nom mais proche il pourra savoir ». Avant, le texte brut (« saif taf du loup »)
partait directement aux sources de lecture : un nom approximatif tombait sur un
mauvais résultat, et YouTube est souvent bloqué depuis Railway.

Ici, une API de CATALOGUE (tolérante aux fautes, classée par pertinence) donne le vrai
titre, l'artiste et la durée ; les sources de lecture sont ensuite interrogées avec ces
informations exactes et matcher.py choisit la bonne version.

Ordre : YouTube Data API (clé ``YOUTUBE_API_KEY``), Spotify (``SPOTIFY_CLIENT_ID`` /
``SPOTIFY_CLIENT_SECRET``), puis Deezer (API publique, sans clé). Chaque étape est
bornée dans le temps ; un échec passe simplement à la suivante.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from collections import OrderedDict
from typing import Any

import aiohttp

from .models import Track

logger = logging.getLogger("bot.music.catalog")

DELAI_SECONDES = 4.0
_TIMEOUT = aiohttp.ClientTimeout(total=DELAI_SECONDES)
_CACHE: "OrderedDict[str, Track | None]" = OrderedDict()
_CACHE_MAX = 500

_DUREE_ISO = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")
_SEPARATEUR = re.compile(r"\s+[-–—|]\s+")
_BRUIT_CHAINE = re.compile(r"\s*(?:-\s*topic|vevo|officiel|official|music)\s*$", re.IGNORECASE)
_BRUIT_TITRE = re.compile(
    r"\s*[\(\[][^\)\]]*(?:clip|officiel|official|audio|video|lyrics?|paroles|visuali[sz]er)[^\)\]]*[\)\]]",
    re.IGNORECASE,
)


def actif() -> bool:
    """Coupé dans les tests et le simulateur (pas de réseau, résultats stables)."""
    return os.environ.get("SENTRIX_MUSIC_CATALOG", "1") != "0"


def cle_youtube() -> str:
    try:
        import config

        valeur = getattr(config, "YOUTUBE_API_KEY", None)
    except Exception:  # noqa: BLE001
        valeur = None
    return str(valeur or os.environ.get("YOUTUBE_API_KEY") or "").strip()


def duree_iso(valeur: str) -> int | None:
    """« PT3M32S » -> 212."""
    match = _DUREE_ISO.match(str(valeur or ""))
    if not match:
        return None
    heures, minutes, secondes = (int(g or 0) for g in match.groups())
    total = heures * 3600 + minutes * 60 + secondes
    return total or None


def depuis_titre_video(titre: str, chaine: str) -> tuple[str, str | None]:
    """« SAÏF - Le taf du loup (Clip officiel) » + « Saïf » -> (« Le taf du loup », « SAÏF »)."""
    propre = _BRUIT_TITRE.sub("", str(titre or "")).strip()
    morceaux = _SEPARATEUR.split(propre, maxsplit=1)
    if len(morceaux) == 2 and morceaux[0] and morceaux[1]:
        return morceaux[1].strip(), morceaux[0].strip()
    artiste = _BRUIT_CHAINE.sub("", str(chaine or "")).strip() or None
    return propre or str(titre or ""), artiste


async def _youtube(session: aiohttp.ClientSession, requete: str, cle: str) -> Track | None:
    params = {
        "part": "snippet", "type": "video", "maxResults": "5", "q": requete,
        "videoCategoryId": "10", "key": cle, "safeSearch": "none",
    }
    async with session.get("https://www.googleapis.com/youtube/v3/search", params=params) as resp:
        if resp.status != 200:
            logger.info("Catalogue YouTube : HTTP %s", resp.status)
            return None
        donnees = await resp.json()
    elements = [e for e in donnees.get("items", []) if (e.get("id") or {}).get("videoId")]
    if not elements:
        # Sans la catégorie Musique (titres rangés ailleurs par l'uploader).
        params.pop("videoCategoryId")
        async with session.get("https://www.googleapis.com/youtube/v3/search", params=params) as resp:
            if resp.status != 200:
                return None
            donnees = await resp.json()
        elements = [e for e in donnees.get("items", []) if (e.get("id") or {}).get("videoId")]
    if not elements:
        return None
    premier = elements[0]
    video_id = premier["id"]["videoId"]
    extrait = premier.get("snippet") or {}
    titre, artiste = depuis_titre_video(extrait.get("title", ""), extrait.get("channelTitle", ""))
    duree = None
    try:
        async with session.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "contentDetails", "id": video_id, "key": cle},
        ) as resp:
            if resp.status == 200:
                infos = await resp.json()
                elements_details = infos.get("items") or [{}]
                duree = duree_iso((elements_details[0].get("contentDetails") or {}).get("duration", ""))
    except aiohttp.ClientError:
        pass
    vignettes = extrait.get("thumbnails") or {}
    vignette = ((vignettes.get("high") or vignettes.get("medium") or vignettes.get("default")) or {}).get("url")
    return Track(
        title=_html(titre), artist=_html(artiste) if artiste else None, duration=duree,
        thumbnail=vignette, original_url=f"https://www.youtube.com/watch?v={video_id}",
        provider="youtube-api",
    )


async def _spotify(session: aiohttp.ClientSession, requete: str, spotify: Any) -> Track | None:
    if spotify is None or not getattr(spotify, "_has_credentials", False):
        return None
    jeton = await spotify._get_token(session)
    async with session.get(
        "https://api.spotify.com/v1/search",
        params={"q": requete, "type": "track", "limit": "1"},
        headers={"Authorization": f"Bearer {jeton}"},
    ) as resp:
        if resp.status != 200:
            logger.info("Catalogue Spotify : HTTP %s", resp.status)
            return None
        donnees = await resp.json()
    pistes = (donnees.get("tracks") or {}).get("items") or []
    if not pistes:
        return None
    piste = pistes[0]
    images = (piste.get("album") or {}).get("images") or [{}]
    return Track(
        title=piste.get("name") or requete,
        artist=", ".join(a.get("name", "") for a in piste.get("artists", [])[:2] if a.get("name")) or None,
        album=(piste.get("album") or {}).get("name"),
        duration=int(piste["duration_ms"] / 1000) if piste.get("duration_ms") else None,
        thumbnail=images[0].get("url"),
        original_url=(piste.get("external_urls") or {}).get("spotify"),
        provider="spotify",
    )


async def _deezer(session: aiohttp.ClientSession, requete: str) -> Track | None:
    async with session.get("https://api.deezer.com/search", params={"q": requete, "limit": "5"}) as resp:
        if resp.status != 200:
            return None
        donnees = await resp.json(content_type=None)
    pistes = donnees.get("data") or []
    if not pistes:
        return None
    piste = pistes[0]
    album = piste.get("album") or {}
    return Track(
        title=piste.get("title") or piste.get("title_short") or requete,
        artist=(piste.get("artist") or {}).get("name"),
        album=album.get("title"),
        duration=piste.get("duration") or None,
        thumbnail=album.get("cover_medium") or album.get("cover"),
        original_url=piste.get("link"),
        provider="deezer",
    )


def _html(texte: str) -> str:
    import html

    return html.unescape(str(texte or ""))


async def identifier(requete: str, *, spotify: Any = None) -> Track | None:
    """Le morceau le plus probable pour ``requete`` (titre exact, artiste, durée), ou None."""
    requete = str(requete or "").strip()
    if not requete or not actif():
        return None
    cle_cache = requete.casefold()
    if cle_cache in _CACHE:
        _CACHE.move_to_end(cle_cache)
        return _CACHE[cle_cache]
    resultat: Track | None = None
    async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
        etapes = []
        cle = cle_youtube()
        if cle:
            etapes.append(("youtube-api", lambda: _youtube(session, requete, cle)))
        etapes.append(("spotify", lambda: _spotify(session, requete, spotify)))
        etapes.append(("deezer", lambda: _deezer(session, requete)))
        for nom, etape in etapes:
            try:
                resultat = await asyncio.wait_for(etape(), DELAI_SECONDES)
            except Exception as exc:  # noqa: BLE001 — une source en panne passe à la suivante
                logger.info("Catalogue %s indisponible : %s", nom, exc)
                resultat = None
            if resultat is not None:
                logger.info(
                    "music catalog -> %r identifié comme %r / %r via %s",
                    requete, resultat.title, resultat.artist, nom,
                )
                break
    if resultat is None:
        return None  # panne ou rien trouvé : on réessaiera la prochaine fois
    _CACHE[cle_cache] = resultat
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return resultat


__all__ = ["actif", "depuis_titre_video", "duree_iso", "identifier"]
