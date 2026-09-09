"""Modèle commun retourné par tous les providers musicaux — voir utils/music/__init__.py
pour l'architecture générale."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Track:
    """Une piste, à n'importe quel stade de résolution.

    `playable_url` est None tant qu'aucune source de lecture autorisée n'a été
    trouvée — c'est la différence entre "on sait ce que l'utilisateur veut" (titre,
    artiste, durée) et "on peut réellement le jouer". `provider` identifie la source
    des MÉTADONNÉES (ex: "spotify") ; `playback_provider` identifie la source du FLUX
    AUDIO réellement utilisé (ex: "youtube") — souvent différente pour Spotify/Deezer,
    qui ne fournissent jamais eux-mêmes de flux audio.
    """

    title: str
    artist: str | None = None
    album: str | None = None
    duration: int | None = None  # secondes ; None si inconnue (ex: direct stream)
    thumbnail: str | None = None
    original_url: str | None = None
    provider: str = "unknown"
    playable_url: str | None = None
    playback_provider: str | None = None
    is_live: bool = False
    requested_by: int | None = None
    # Métadonnées internes au matching — jamais affichées à l'utilisateur.
    match_score: float = field(default=0.0, repr=False, compare=False)
    variant_tags: tuple[str, ...] = field(default=(), repr=False, compare=False)

    @property
    def is_playable(self) -> bool:
        return bool(self.playable_url)

    def display_title(self) -> str:
        if self.artist and self.artist.casefold() not in self.title.casefold():
            return f"{self.artist} — {self.title}"
        return self.title
