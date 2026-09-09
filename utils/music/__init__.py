"""Moteur musique multi-provider de SentriX.

Remplace l'ancien système (cogs/music.py historique) qui envoyait TOUTE requête —
recherche par titre, lien Spotify, lien Deezer — directement à yt-dlp/YouTube. Sur
Railway, l'IP du datacenter est régulièrement bloquée par YouTube ("Sign in to
confirm you're not a bot" / erreur générique) : comme YouTube était l'unique source,
un seul blocage cassait toute la musique, y compris pour un lien Spotify qui n'a
techniquement rien à voir avec YouTube.

Architecture (voir chaque sous-module pour le détail) :

    requête utilisateur
      -> ProviderManager.resolve() (manager.py)
      -> détection de plateforme (provider.matches())
      -> résolution des métadonnées (provider.resolve_metadata())
      -> si le provider ne fournit pas lui-même l'audio (Spotify/Deezer = métadonnées
         SEULEMENT, jamais de flux) : recherche de candidats de lecture chez les
         providers qui EN fournissent (YouTube, SoundCloud, audio direct), classés par
         matcher.py (titre/artiste/durée, écarte nightcore/slowed/cover/remix/karaoke
         sauf demande explicite)
      -> tentative source 1 -> échec (provider.ProviderUnavailable) -> source 2 -> ...
      -> lecture, ou errors.NoPlayableSource si tout échoue.

Chaque provider est indépendant (providers/base.py::MusicProvider) et retourne un
modèle commun (models.py::Track). Un provider qui reçoit un challenge anti-bot lève
ProviderUnavailable et est marqué indisponible temporairement (manager.py) — il
n'empêche jamais les autres sources d'être tentées.
"""
from .models import Track
from .errors import MusicEngineError, ProviderUnavailable, TrackNotFound, NoPlayableSource
from .manager import ProviderManager, ResolvedRequest

__all__ = [
    "Track",
    "MusicEngineError",
    "ProviderUnavailable",
    "TrackNotFound",
    "NoPlayableSource",
    "ProviderManager",
    "ResolvedRequest",
]
