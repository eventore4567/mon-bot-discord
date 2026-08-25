"""SentriX V3.6.1 — protège le markup Discord des emojis animés.

Certaines anciennes couches de typographie traitaient le caractère ``<`` d'un emoji
Discord ``<a:nom:id>`` comme une décoration et le supprimaient. Discord affichait alors
``a:nom:id>`` en texte brut. Ce garde protège le token complet et nettoie également les
fragments V3.6 déjà cassés lorsqu'un panneau est régénéré.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from discord.ext import commands

from utils import premium_style

logger = logging.getLogger("bot.sentrix-emoji-markup-v361")

_CUSTOM_PREFIX_RE = re.compile(r"^\s*(<a?:[A-Za-z0-9_~]+:\d+>)\s*")
_BROKEN_V36_RE = re.compile(r"(?<!<)(?:a:|:)?sxv36_[A-Za-z0-9_~]+:\d+>")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_INSTALLED = False


def _repair_broken(value: Any) -> str:
    text = str(value or "")
    text = _BROKEN_V36_RE.sub("", text)
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

    clean_title_with_custom_emoji._sentrix_custom_emoji_safe_v361 = True
    clean_title_with_custom_emoji._sentrix_original = original_clean_title
    premium_style.clean_title = clean_title_with_custom_emoji

    try:
        from . import sentrix_emoji_runtime as animated

        original_replace = animated._replace_known_tokens
        if not getattr(original_replace, "_sentrix_markup_safe_v361", False):
            def replace_known_tokens_safe(value: Any) -> str:
                return _repair_broken(original_replace(value))

            replace_known_tokens_safe._sentrix_markup_safe_v361 = True
            replace_known_tokens_safe._sentrix_original = original_replace
            animated._replace_known_tokens = replace_known_tokens_safe
    except Exception:
        logger.exception("Le nettoyeur des fragments emojis V3.6 n'a pas pu être branché.")

    _INSTALLED = True
    logger.info("SentriX V3.6.1 : markup <a:emoji:id> protégé et fragments cassés réparés.")


__all__ = ["install", "_repair_broken"]
