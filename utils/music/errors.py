"""Exceptions du moteur musique — voir utils/music/__init__.py pour l'architecture."""
from __future__ import annotations


class MusicEngineError(Exception):
    """Base commune, jamais levée directement."""


class ProviderUnavailable(MusicEngineError):
    """Le provider a répondu par un challenge anti-bot, un rate-limit ou une erreur
    réseau temporaire — PAS "ce morceau n'existe pas". Le ProviderManager marque ce
    provider indisponible pour un court délai et passe au suivant sans jamais faire
    échouer la requête utilisateur à cause d'un seul provider en panne."""

    def __init__(self, provider: str, reason: str):
        self.provider = provider
        self.reason = reason
        super().__init__(f"{provider} indisponible : {reason}")


class TrackNotFound(MusicEngineError):
    """Le provider a compris la requête (URL reconnue) mais rien ne correspond
    (morceau supprimé/privé/région verrouillée)."""

    def __init__(self, provider: str, query: str):
        self.provider = provider
        self.query = query
        super().__init__(f"{provider} : aucun résultat pour {query!r}")


class NoPlayableSource(MusicEngineError):
    """Métadonnées résolues avec succès, mais AUCUNE source de lecture autorisée
    n'a pu être trouvée après avoir épuisé tous les providers de lecture — jamais un
    message générique "vérifie ton lien" quand le lien était en fait correct."""

    def __init__(self, title: str, attempted_providers: list[str]):
        self.title = title
        self.attempted_providers = attempted_providers
        super().__init__(
            f"Aucune source de lecture autorisée pour {title!r} "
            f"(essayé : {', '.join(attempted_providers) or 'aucun'})"
        )
