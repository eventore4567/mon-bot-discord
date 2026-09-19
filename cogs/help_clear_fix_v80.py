"""SentriX V80 — Help sans faux ping.

Les textes du Help n'affichent plus @everyone/@here comme de vraies mentions Discord.
(Le journal complet de +clear — aperçu, transcription, suppression des cartes
individuelles — vit désormais dans cogs/moderation.py::Moderation.clear.)
"""
from __future__ import annotations

import logging
import re

from discord.ext import commands

from . import help_complete_v79 as help_v79
from . import premium_ui_v81 as premium_v81
from . import premium_ui_v82 as premium_v82

logger = logging.getLogger("bot.help-clear-fix-v80")
RUNTIME_MARKER = "Help/Clear Fix V80"
_PRIVATE_HELP_ROOTS = frozenset({
    "bl", "blinfo", "unbl", "editbl", "sync", "syncguild", "wipe-server",
})


def _neutralize_mentions(value: object) -> str:
    """Garde le texte lisible sans transformer @everyone/@here en mention Discord."""
    text = str(value or "")
    return re.sub(r"@(everyone|here)\b", lambda m: "@\u200b" + m.group(1), text, flags=re.IGNORECASE)


def _install_help_safety() -> None:
    current_catalog = help_v79._catalog
    if not getattr(current_catalog, "_sentrix_v80_private_owner_filter", False):
        def safe_catalog(bot):
            rows = current_catalog(bot)
            return [
                entry for entry in rows
                if help_v79._normalise(entry.key).split(" ", 1)[0] not in _PRIVATE_HELP_ROOTS
            ]

        safe_catalog._sentrix_v80_private_owner_filter = True
        safe_catalog._sentrix_previous = current_catalog
        help_v79._catalog = safe_catalog

    current_description = help_v79._description
    if not getattr(current_description, "_sentrix_v80_safe_mentions", False):
        def safe_description(entry):
            return _neutralize_mentions(current_description(entry))

        safe_description._sentrix_v80_safe_mentions = True
        safe_description._sentrix_previous = current_description
        help_v79._description = safe_description

    current_permission = help_v79._permission
    if not getattr(current_permission, "_sentrix_v80_safe_mentions", False):
        def safe_permission(entry):
            return _neutralize_mentions(current_permission(entry))

        safe_permission._sentrix_v80_safe_mentions = True
        safe_permission._sentrix_previous = current_permission
        help_v79._permission = safe_permission

    current_example = help_v79._example
    if not getattr(current_example, "_sentrix_v80_safe_mentions", False):
        def safe_example(entry, prefix):
            return _neutralize_mentions(current_example(entry, prefix))

        safe_example._sentrix_v80_safe_mentions = True
        safe_example._sentrix_previous = current_example
        help_v79._example = safe_example


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_help_clear_fix_v80", False):
        return
    _install_help_safety()
    premium_v81.install(bot)
    premium_v82.install(bot)
    bot._sentrix_help_clear_fix_v80 = True
    logger.info(
        "%s installé : mentions du Help neutralisées, commandes owner privées masquées et Premium UI V82 chargée.",
        RUNTIME_MARKER,
    )


__all__ = ["install", "_neutralize_mentions"]
