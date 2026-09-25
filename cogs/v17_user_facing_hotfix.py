"""Correctifs utilisateur finaux de SentriX.

Cette couche garde les correctifs généraux d'interface/compatibilité et garantit qu'une
seule famille de commandes ``+create`` reste enregistrée.
"""
from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

logger = logging.getLogger("bot.v17-user-facing-hotfix")

_DISPATCH_PATCHED = False
_PLAIN_INSTALL_PATCHED = False
PREFIX_ERROR_LIFETIME = 12.0


def _patch_error_dispatch() -> None:
    """Marque le Context avant que les handlers/listeners d'erreur soient planifiés."""
    global _DISPATCH_PATCHED
    if _DISPATCH_PATCHED:
        return

    current_dispatch = commands.Bot.dispatch
    if getattr(current_dispatch, "_sentrix_private_command_errors", False):
        _DISPATCH_PATCHED = True
        return

    def error_dispatch(self: commands.Bot, event_name: str, /, *args: Any, **kwargs: Any):
        if event_name == "command_error" and args:
            ctx = args[0]
            if isinstance(ctx, commands.Context):
                ctx._sentrix_private_error = True
        return current_dispatch(self, event_name, *args, **kwargs)

    error_dispatch._sentrix_private_command_errors = True
    error_dispatch._sentrix_original = current_dispatch
    commands.Bot.dispatch = error_dispatch
    _DISPATCH_PATCHED = True


def _apply_error_context_transport() -> None:
    """Slash = ephemeral. Préfixe = réponse locale temporaire, jamais un DM automatique."""
    current_send = commands.Context.send
    if getattr(current_send, "_sentrix_error_transport_v2", False):
        return

    async def error_send(self: commands.Context, *args, **kwargs):
        if not getattr(self, "_sentrix_private_error", False):
            return await current_send(self, *args, **kwargs)

        interaction = getattr(self, "interaction", None)
        if interaction is not None:
            kwargs["ephemeral"] = True
            return await current_send(self, *args, **kwargs)

        kwargs.pop("ephemeral", None)
        kwargs.setdefault("delete_after", PREFIX_ERROR_LIFETIME)
        kwargs.setdefault("allowed_mentions", discord.AllowedMentions.none())
        message = getattr(self, "message", None)
        # Pas de reference= ici : current_send a été capturé AVANT l'installation de
        # cogs/reply_reference_fix.py, donc un reference= posé à ce niveau contournait
        # entièrement son filtrage et atteignait l'envoi Discord réel — réintroduisant
        # le bandeau "le message original a été supprimé" que reply_reference_fix.py
        # existe pour éliminer, mais seulement sur les erreurs de commandes préfixées.
        # Voir docs/core-v2-audit-technical-debt.md §8.

        try:
            result = await current_send(self, *args, **kwargs)
            self._sentrix_response_sent = True
            return result
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            try:
                if message is not None:
                    await message.add_reaction("❌")
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass
            self._sentrix_response_sent = True
            return None

    error_send._sentrix_error_transport_v2 = True
    error_send._sentrix_original = current_send
    commands.Context.send = error_send


def _patch_plain_response_install() -> None:
    """Réapplique le transport d'erreur après chaque réinstallation du rendu final."""
    global _PLAIN_INSTALL_PATCHED
    if _PLAIN_INSTALL_PATCHED:
        return

    from . import plain_response_policy

    current_install = plain_response_policy.install
    if getattr(current_install, "_sentrix_error_install_v2", False):
        _PLAIN_INSTALL_PATCHED = True
        return

    def install_with_error_policy(bot: commands.Bot | None = None) -> None:
        current_install(bot)
        _apply_error_context_transport()

    install_with_error_policy._sentrix_error_install_v2 = True
    install_with_error_policy._sentrix_original = current_install
    plain_response_policy.install = install_with_error_policy
    _PLAIN_INSTALL_PATCHED = True


async def install(bot: commands.Bot, extension_name: str = "") -> None:
    """Trois correctifs V17. Il y en avait un quatrième, retiré.

    ``_patch_duplicate_mention`` enveloppait ``common_command_names._mention_help``
    pour empêcher une deuxième réponse à une mention nue. Cette fonction n'existe
    plus — le pipeline V5 est devenu l'unique autorité, et un test interdit son
    retour. Le correctif levait donc un ``AttributeError`` à CHAQUE démarrage,
    avalé par ``bot_v17_major`` en « module non appliqué » : une trace d'erreur
    permanente en production, pour un doublon devenu structurellement impossible.
    """
    del extension_name
    _patch_error_dispatch()
    _patch_plain_response_install()
    _apply_error_context_transport()


__all__ = ["install"]
