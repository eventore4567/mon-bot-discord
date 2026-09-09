"""Chaque provider est indépendant et ne connaît rien des autres — voir
utils/music/__init__.py pour l'architecture générale et la place de chaque
provider dans le pipeline de résolution."""
from .base import MusicProvider
from .youtube import YouTubeProvider
from .soundcloud import SoundCloudProvider
from .spotify import SpotifyProvider
from .deezer import DeezerProvider
from .direct_audio import DirectAudioProvider
from .search import SearchProvider

__all__ = [
    "MusicProvider",
    "YouTubeProvider",
    "SoundCloudProvider",
    "SpotifyProvider",
    "DeezerProvider",
    "DirectAudioProvider",
    "SearchProvider",
]
