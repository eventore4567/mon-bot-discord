"""SentriX V3.7 — garde anti-fragments pour les emojis Discord.

Protège les vrais tokens ``<a:nom:id>`` avant tout nettoyage et retire seulement les
anciens fragments cassés ``a a a``, ``<a`` ou ``sxv36/sxv37`` incomplets.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from discord.ext import commands

from utils import premium_style

logger = logging.getLogger("bot.sentrix-emoji-markup-v37")

_CUSTOM_EMOJI_RE = re.compile(r"<a?:[A-Za-z0-9_~]+:\d+>")
_CUSTOM_PREFIX_RE = re.compile(r"^\s*(<a?:[A-Za-z0-9_~]+:\d+>)\s*")
_BROKEN_PACK_RE = re.compile(r"(?<![A-Za-z0-9_])(?:<?a?:?|:)?sxv(?:36|37)_[A-Za-z0-9_~]+:\d+>", re.I)
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_INSTALLED = False


def _repair_broken(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""

    protected: dict[str, str] = {}
    def protect(match: re.Match[str]) -> str:
        key = f"\x00SXSAFE{len(protected)}\x00"
        protected[key] = match.group(0)
        return key

    text = _CUSTOM_EMOJI_RE.sub(protect, text)
    text = _BROKEN_PACK_RE.sub("", text)
    text = re.sub(r"(?m)^\s*<a\s+(?=\S)", "", text, flags=re.I)
    text = re.sub(r"(?m)^\s*(?:a\s+){2,8}(?=\S)", "", text, flags=re.I)
    text = _MULTI_SPACE_RE.sub(" ", text)
    text = re.sub(r" +\n", "\n", text)
    text = text.strip()
    for key, token in protected.items():
        text = text.replace(key, token)
    return text


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

    clean_title_with_custom_emoji._sentrix_custom_emoji_safe_v37 = True
    clean_title_with_custom_emoji._sentrix_original = original_clean_title
    premium_style.clean_title = clean_title_with_custom_emoji

    try:
        from . import sentrix_emoji_runtime as ui

        original_clean = ui._clean_artifacts
        if not getattr(original_clean, "_sentrix_guard_v37", False):
            def guarded_clean(value: Any) -> str:
                return _repair_broken(value)
            guarded_clean._sentrix_guard_v37 = True
            guarded_clean._sentrix_original = original_clean
            ui._clean_artifacts = guarded_clean

        original_strip = ui._strip_existing_icon
        if not getattr(original_strip, "_sentrix_legacy_marker_fix_v37", False):
            def strip_legacy_marker(value: Any) -> str:
                text = original_strip(value)
                text = re.sub(r"^[⌕✦✓✕▶◀]+\s*", "", text).strip()
                return _repair_broken(text)
            strip_legacy_marker._sentrix_legacy_marker_fix_v37 = True
            strip_legacy_marker._sentrix_original = original_strip
            ui._strip_existing_icon = strip_legacy_marker

        original_body = ui._clean_body
        if not getattr(original_body, "_sentrix_body_clarity_v37", False):
            def clear_body(value: Any) -> str:
                text = _repair_broken(original_body(value))
                text = text.replace("🎮 Communauté & progression", "🌍 Communauté & progression")
                text = text.replace("🎮 Community & progression", "🌍 Community & progression")
                return text
            clear_body._sentrix_body_clarity_v37 = True
            clear_body._sentrix_original = original_body
            ui._clean_body = clear_body

        original_static_icon = ui._static_icon
        if not getattr(original_static_icon, "_sentrix_setup_clarity_v37", False):
            def clear_static_icon(text: Any, *, category: str | None = None) -> str:
                haystack = str(text or "").casefold()
                specific = (
                    ("⚙️", ("centre de contrôle", "centre de controle", "control center")),
                    ("🌐", ("serveur", "server")),
                    ("📈", ("progression", "progress")),
                    ("🌍", ("langue", "language")),
                    ("🧩", ("modules", "systèmes principaux", "systemes principaux", "main systems")),
                    ("📡", ("en direct", "live")),
                    ("ℹ️", ("information", "informations")),
                )
                for icon, words in specific:
                    if any(word in haystack for word in words):
                        return icon
                return original_static_icon(text, category=category)
            clear_static_icon._sentrix_setup_clarity_v37 = True
            clear_static_icon._sentrix_original = original_static_icon
            ui._static_icon = clear_static_icon

        original_button_icon = ui._button_icon
        if not getattr(original_button_icon, "_sentrix_button_clarity_v37", False):
            def clear_button_icon(text: str):
                haystack = str(text or "").casefold()
                if "résumé" in haystack or "resume" in haystack or "summary" in haystack:
                    return "📋"
                if "historique" in haystack or "history" in haystack:
                    return "🕘"
                if "dashboard" in haystack or "tableau de bord" in haystack:
                    return "🌐"
                return original_button_icon(text)
            clear_button_icon._sentrix_button_clarity_v37 = True
            clear_button_icon._sentrix_original = original_button_icon
            ui._button_icon = clear_button_icon
    except Exception:
        logger.exception("Le garde visuel V3.7 n'a pas pu être branché.")

    _INSTALLED = True
    logger.info("SentriX V3.7 : tokens custom protégés et fragments sxv36/sxv37 nettoyés.")


__all__ = ["install", "_repair_broken"]
