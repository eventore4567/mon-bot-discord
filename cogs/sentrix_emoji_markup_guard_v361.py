"""SentriX V3.6.2 — garde anti-fragments pour le markup des emojis Discord.

La V3.6.2 utilise des emojis Unicode simples pour la navigation et réserve les emojis
animés aux états. Ce garde protège toujours un vrai ``<a:nom:id>`` et nettoie les anciens
fragments V3.6 (`a a a`, `<a`, `a:sxv36_...>`) avant tout passage dans la typographie.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from discord.ext import commands

from utils import premium_style

logger = logging.getLogger("bot.sentrix-emoji-markup-v361")

_CUSTOM_PREFIX_RE = re.compile(r"^\s*(<a?:[A-Za-z0-9_~]+:\d+>)\s*")
_BROKEN_V36_RE = re.compile(r"(?<![A-Za-z0-9_])(?:<?a?:?|:)?sxv36_[A-Za-z0-9_~]+:\d+>", re.I)
_BROKEN_PREFIX_RE = re.compile(r"^\s*(?:(?:<a|a)(?:\s+|(?=[A-ZÀ-ÖØ-Þ]))){1,8}", re.I)
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_INSTALLED = False


def _repair_broken(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    text = _BROKEN_V36_RE.sub("", text)
    text = _BROKEN_PREFIX_RE.sub("", text)
    # Corrige aussi les fragments placés au début des lignes d'une liste/champ.
    text = re.sub(r"(?m)^\s*<a\s+(?=\S)", "", text, flags=re.I)
    text = re.sub(r"(?m)^\s*(?:a\s+){2,8}(?=\S)", "", text, flags=re.I)
    text = _MULTI_SPACE_RE.sub(" ", text)
    text = re.sub(r" +\n", "\n", text)
    return text.strip()


def install(bot: commands.Bot) -> None:
    del bot
    global _INSTALLED
    if _INSTALLED:
        return

    original_clean_title = premium_style.clean_title

    def clean_title_with_custom_emoji(value: Any, fallback: str = "Information") -> str:
        text = _repair_broken(value)
        if not text:
            return fallback

        match = _CUSTOM_PREFIX_RE.match(text)
        if match is None:
            return original_clean_title(text, fallback)

        token = match.group(1)
        remainder = _repair_broken(text[match.end():])
        if not remainder:
            return token
        cleaned = original_clean_title(remainder, fallback="")
        if not cleaned:
            return token
        return premium_style.clip(f"{token} {cleaned}", 256)

    clean_title_with_custom_emoji._sentrix_custom_emoji_safe_v362 = True
    clean_title_with_custom_emoji._sentrix_original = original_clean_title
    premium_style.clean_title = clean_title_with_custom_emoji

    try:
        from . import sentrix_emoji_runtime as ui

        original_clean = ui._clean_artifacts
        if not getattr(original_clean, "_sentrix_guard_v362", False):
            def guarded_clean(value: Any) -> str:
                return _repair_broken(original_clean(value))

            guarded_clean._sentrix_guard_v362 = True
            guarded_clean._sentrix_original = original_clean
            ui._clean_artifacts = guarded_clean

        original_strip = ui._strip_existing_icon
        if not getattr(original_strip, "_sentrix_legacy_marker_fix_v362", False):
            def strip_legacy_marker(value: Any) -> str:
                text = original_strip(value)
                # Ancien symbole de recherche/help qui n'est pas dans le bloc emoji Unicode.
                text = re.sub(r"^[⌕✦✓✕▶◀]+\s*", "", text).strip()
                return _repair_broken(text)

            strip_legacy_marker._sentrix_legacy_marker_fix_v362 = True
            strip_legacy_marker._sentrix_original = original_strip
            ui._strip_existing_icon = strip_legacy_marker

        original_body = ui._clean_body
        if not getattr(original_body, "_sentrix_body_clarity_v362", False):
            def clear_body(value: Any) -> str:
                text = _repair_broken(original_body(value))
                # Le bloc principal de +help utilisait l'icône jeu pour « Communauté ».
                text = text.replace("🎮 Communauté & progression", "🌍 Communauté & progression")
                text = text.replace("🎮 Community & progression", "🌍 Community & progression")
                return text

            clear_body._sentrix_body_clarity_v362 = True
            clear_body._sentrix_original = original_body
            ui._clean_body = clear_body
    except Exception:
        logger.exception("Le garde visuel V3.6.2 n'a pas pu être branché.")

    _INSTALLED = True
    logger.info("SentriX V3.6.2 : fragments cassés supprimés et anciens marqueurs help nettoyés.")


__all__ = ["install", "_repair_broken"]
