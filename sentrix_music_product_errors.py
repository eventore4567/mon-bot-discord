"""Messages d'erreur musique utiles pour la surface produit SentriX."""
from __future__ import annotations

import logging

from discord.ext import commands

from utils.music import NoPlayableSource, ProviderUnavailable, TrackNotFound

logger = logging.getLogger("bot.music-product-errors")
_INSTALLED = False


def _classify(exc) -> tuple[str, str]:
    if isinstance(exc, TrackNotFound):
        provider = str(getattr(exc, "provider", "source") or "source").title()
        return (
            "Titre introuvable",
            f"{provider} a reconnu la requête, mais aucun titre exploitable n'a été trouvé.",
        )

    if isinstance(exc, ProviderUnavailable):
        provider = str(getattr(exc, "provider", "source") or "source")
        reason = str(getattr(exc, "reason", "") or "")
        lowered = reason.casefold()
        if provider.casefold() == "spotify" and "spotify_client_id" in lowered:
            return (
                "Spotify non configuré",
                "L'import d'un album ou d'une playlist Spotify nécessite la configuration "
                "de l'application Spotify côté Railway. Une piste Spotify individuelle reste "
                "utilisable via ses métadonnées publiques.",
            )
        if "429" in lowered or "rate" in lowered:
            return (
                f"{provider.title()} temporairement limité",
                "Le fournisseur limite actuellement les requêtes. Réessayez dans quelques instants.",
            )
        if "403" in lowered or "forbidden" in lowered or "challenge" in lowered:
            return (
                f"{provider.title()} indisponible",
                "Le fournisseur refuse temporairement la lecture depuis l'hébergement actuel. "
                "SentriX essaiera les autres sources autorisées lorsqu'elles sont disponibles.",
            )
        return (
            f"{provider.title()} indisponible",
            "Le fournisseur de musique est temporairement indisponible. Réessayez dans quelques instants.",
        )

    if isinstance(exc, NoPlayableSource):
        attempted = [str(item) for item in getattr(exc, "attempted_providers", []) if item]
        suffix = f" Sources essayées : {', '.join(attempted)}." if attempted else ""
        return (
            "Aucune source audio disponible",
            "Les métadonnées ont été trouvées, mais aucune source de lecture autorisée n'a pu être ouverte."
            + suffix,
        )

    return (
        "Lecture impossible",
        "SentriX n'a pas pu résoudre cette requête musicale. Consultez les détails du fournisseur et réessayez.",
    )


def _patch_music_module(cog) -> None:
    try:
        module = __import__(cog.__class__.__module__, fromlist=["_classify_engine_error"])
        module._classify_engine_error = _classify
        cog._sentrix_product_errors = True
        logger.warning("Messages d'erreur musique précis activés.")
    except Exception:
        logger.exception("Impossible d'installer les messages d'erreur musique précis.")


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    original = commands.Bot.add_cog
    if getattr(original, "_sentrix_music_product_errors_loader", False):
        _INSTALLED = True
        return

    async def add_cog_with_product_errors(bot, cog, *args, **kwargs):
        result = await original(bot, cog, *args, **kwargs)
        if cog.__class__.__name__ == "Music" or getattr(cog, "qualified_name", None) == "Music":
            _patch_music_module(cog)
        return result

    add_cog_with_product_errors._sentrix_music_product_errors_loader = True
    add_cog_with_product_errors.__wrapped__ = original
    commands.Bot.add_cog = add_cog_with_product_errors
    _INSTALLED = True


__all__ = ["install"]
