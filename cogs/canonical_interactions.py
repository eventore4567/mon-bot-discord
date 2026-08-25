"""Compatibilité du runtime d'interactions SentriX.

Ce module ne possède PLUS le rendu Discord. L'ancienne implémentation transformait
volontairement les embeds en texte puis se réappliquait sur ``on_ready`` ; elle annulait
donc le design system officiel après le chargement du bot.

Le seul rôle conservé ici est le nettoyage des anciens watchdogs slash devenus inutiles.
Le rendu des commandes appartient exclusivement à ``cogs.final_interaction_policy``.
"""
from __future__ import annotations

import logging

from discord.ext import commands

logger = logging.getLogger("bot.canonical-interactions")

_BLOCKED_MODULES = {
    "cogs.slash_reliability_v7",
    "cogs.deferred_context_response_guard",
    "cogs.slash_error_completion_guard",
}


def remove_old_slash_listeners(bot: commands.Bot) -> int:
    """Retire uniquement les anciens watchdogs slash concurrents."""
    removed = 0
    extra_events = getattr(bot, "extra_events", {})
    for event_name, listeners in list(extra_events.items()):
        for callback in list(listeners):
            if getattr(callback, "__module__", "") not in _BLOCKED_MODULES:
                continue
            try:
                bot.remove_listener(callback, event_name)
                removed += 1
            except Exception:
                logger.debug("Listener slash historique impossible à retirer.", exc_info=True)

    for attr in ("_sentrix_slash_relay_task", "_sentrix_slash_startup_task"):
        task = getattr(bot, attr, None)
        if task is not None and hasattr(task, "cancel") and not task.done():
            task.cancel()
    bot._sentrix_canonical_removed_listeners = removed
    return removed


def install(bot: commands.Bot) -> int:
    removed = remove_old_slash_listeners(bot)
    bot._sentrix_canonical_interactions = False
    bot._sentrix_canonical_cleanup_only = True
    logger.info(
        "Compatibilité interactions : aucun embed aplati en texte ; %s watchdog(s) slash retiré(s).",
        removed,
    )
    return removed


async def setup(bot: commands.Bot) -> None:
    install(bot)


__all__ = ["install", "remove_old_slash_listeners"]
