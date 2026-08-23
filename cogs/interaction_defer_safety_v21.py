"""SentriX V21 — defer/typing slash idempotents.

Plusieurs commandes hybrides IA font volontairement un ``await ctx.defer()`` immédiat,
puis utilisent ensuite ``async with ctx.typing()`` pendant l'appel réseau. Dans discord.py,
le contexte de typing d'une interaction peut tenter un nouveau defer. Une interaction ne
peut être acquittée qu'une fois : le second defer provoque alors InteractionResponded et
fait échouer la commande alors que l'appel IA lui-même est valide.

Cette couche rend uniquement l'acquittement idempotent :
- un premier defer reste strictement inchangé ;
- si l'interaction a déjà répondu/defer, un defer supplémentaire devient un no-op ;
- un ``ctx.typing()`` demandé après defer devient aussi un contexte async no-op, car le
  client Discord affiche déjà l'état d'attente de l'interaction.

Aucune réponse, permission, logique IA ou callback métier n'est modifié.
"""
from __future__ import annotations

import logging

from discord.ext import commands

logger = logging.getLogger("bot.interaction-defer-safety-v21")


class _CompletedInteractionTyping:
    """Compatible avec ``async with`` et ``await`` sans envoyer un second defer."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def __await__(self):
        async def _done():
            return None
        return _done().__await__()


def install(bot: commands.Bot | None = None, extension_name: str = "") -> None:
    del bot, extension_name

    current_defer = getattr(commands.Context, "defer", None)
    if current_defer is not None and not getattr(current_defer, "_sentrix_idempotent_defer_v21", False):
        async def defer_safe(self: commands.Context, *args, **kwargs):
            interaction = getattr(self, "interaction", None)
            if interaction is not None:
                try:
                    if interaction.response.is_done():
                        return None
                except Exception:
                    pass
            return await current_defer(self, *args, **kwargs)

        # Ne pas publier `_sentrix_original` ici : certaines anciennes couches déroulent
        # automatiquement cette chaîne et contourneraient alors précisément ce garde final.
        defer_safe._sentrix_idempotent_defer_v21 = True
        commands.Context.defer = defer_safe

    current_typing = getattr(commands.Context, "typing", None)
    if current_typing is not None and not getattr(current_typing, "_sentrix_idempotent_typing_v21", False):
        def typing_safe(self: commands.Context, *args, **kwargs):
            interaction = getattr(self, "interaction", None)
            if interaction is not None:
                try:
                    if interaction.response.is_done():
                        return _CompletedInteractionTyping()
                except Exception:
                    pass
            return current_typing(self, *args, **kwargs)

        typing_safe._sentrix_idempotent_typing_v21 = True
        commands.Context.typing = typing_safe

    logger.info("V21 : defer et typing slash idempotents actifs.")


__all__ = ["install"]
