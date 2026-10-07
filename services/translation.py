"""Service de traduction — déterministe, sans IA, sans type discord.py.

Fournisseur : Google Translate via la bibliothèque `deep-translator`. Pas de
modèle de langage : le brief SentriX exclut l'IA pour les traductions.

Ce qui a motivé ce module (constaté le 07/10/2026)
--------------------------------------------------
- `deep-translator` n'était PAS dans requirements.txt : en production l'import
  échouait à chaque appel, et /translate répondait toujours « Vérifiez le code de
  langue » — un message qui accusait l'utilisateur d'une panne qui n'était pas
  la sienne.
- L'appel était SYNCHRONE dans une coroutine : pendant chaque traduction, tout le
  bot était figé (aucun message, aucune commande traités). Il s'exécute
  désormais dans un fil séparé, avec un délai maximal.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable

#: Langues proposées en premier (brief SentriX, point 31). Le fournisseur en
#: accepte d'autres : un code inconnu de cette liste reste essayé.
LANGUAGES: dict[str, str] = {
    "en": "English",
    "fr": "Français",
    "es": "Español",
    "de": "Deutsch",
    "it": "Italiano",
    "pt": "Português",
    "ar": "العربية",
    "ja": "日本語",
    "ko": "한국어",
    "zh-CN": "中文 (简体)",
    "ru": "Русский",
    "nl": "Nederlands",
    "pl": "Polski",
    "tr": "Türkçe",
    "uk": "Українська",
    "hi": "हिन्दी",
}

#: Noms courants tapés à la place du code.
ALIASES: dict[str, str] = {
    "english": "en", "anglais": "en", "french": "fr", "francais": "fr", "français": "fr",
    "spanish": "es", "espagnol": "es", "german": "de", "allemand": "de",
    "italian": "it", "italien": "it", "portuguese": "pt", "portugais": "pt",
    "arabic": "ar", "arabe": "ar", "japanese": "ja", "japonais": "ja",
    "korean": "ko", "coreen": "ko", "coréen": "ko", "chinese": "zh-CN", "chinois": "zh-CN",
    "zh": "zh-CN", "russian": "ru", "russe": "ru",
}

MAX_LENGTH = 4500      # Google refuse au-delà de 5000 caractères.
TIMEOUT_SECONDS = 12.0


class TranslationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Translation:
    text: str
    target: str
    source: str          # « auto » si la langue d'origine n'a pas été fournie


def normalise_language(value: str | None) -> str:
    """« FR », « français », « pt-BR », « zh » -> code accepté par le fournisseur."""
    raw = str(value or "").strip()
    if not raw:
        raise TranslationError("missing_language")
    lowered = raw.casefold()
    if lowered in ALIASES:
        return ALIASES[lowered]
    for code in LANGUAGES:
        if code.casefold() == lowered:
            return code
    if "-" in raw:
        base = raw.split("-", 1)[0].casefold()
        if base == "zh":
            return "zh-TW" if raw.upper().endswith(("TW", "HK")) else "zh-CN"
        return base
    return lowered


def locale_to_language(locale: Any) -> str:
    """Langue Discord de l'utilisateur (« fr », « en-US », « pt-BR »…) -> code."""
    value = str(getattr(locale, "value", locale) or "en")
    try:
        return normalise_language(value)
    except TranslationError:
        return "en"


def suggestions(current: str, limit: int = 25) -> list[tuple[str, str]]:
    """Langues à proposer en autocomplétion : (libellé, code)."""
    needle = str(current or "").casefold()
    out: list[tuple[str, str]] = []
    for code, name in LANGUAGES.items():
        if not needle or needle in code.casefold() or needle in name.casefold():
            out.append((f"{name} ({code})", code))
    return out[:limit]


def _google(text: str, source: str, target: str) -> str:
    from deep_translator import GoogleTranslator

    return GoogleTranslator(source=source, target=target).translate(text)


async def translate(
    text: str,
    target: str,
    *,
    source: str = "auto",
    provider: Callable[[str, str, str], str] | None = None,
) -> Translation:
    """Traduit `text` vers `target`. Lève TranslationError avec un code stable."""
    text = str(text or "").strip()
    if not text:
        raise TranslationError("empty")
    if len(text) > MAX_LENGTH:
        raise TranslationError("too_long")
    target_code = normalise_language(target)
    source_code = "auto" if str(source or "auto").strip().casefold() == "auto" else normalise_language(source)
    call = provider or _google
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(call, text, source_code, target_code), TIMEOUT_SECONDS,
        )
    except TranslationError:
        raise
    except asyncio.TimeoutError as exc:
        raise TranslationError("unavailable") from exc
    except ImportError as exc:
        raise TranslationError("unavailable") from exc
    except Exception as exc:  # noqa: BLE001 — le fournisseur lève des types variés
        name = type(exc).__name__.casefold()
        if "language" in name or "notsupported" in name or "invalid" in name:
            raise TranslationError("unsupported_language") from exc
        raise TranslationError("unavailable") from exc
    if not str(result or "").strip():
        raise TranslationError("unavailable")
    return Translation(text=str(result), target=target_code, source=source_code)


__all__ = [
    "LANGUAGES", "MAX_LENGTH", "Translation", "TranslationError",
    "locale_to_language", "normalise_language", "suggestions", "translate",
]
