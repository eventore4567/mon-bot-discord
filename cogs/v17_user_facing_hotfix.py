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
_MENTION_PATCHED = False
_PLAIN_INSTALL_PATCHED = False
_LANGUAGE_JOIN_PATCHED = False
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
        if message is not None:
            kwargs.setdefault("reference", message)
            kwargs.setdefault("mention_author", False)

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


def _patch_duplicate_mention() -> None:
    """Désactive l'ancienne carte Utilitaires quand le nouvel accueil est disponible."""
    global _MENTION_PATCHED
    if _MENTION_PATCHED:
        return

    from . import common_command_names

    current = common_command_names._mention_help
    if getattr(current, "_sentrix_compact_home_guard", False):
        _MENTION_PATCHED = True
        return

    async def mention_help_without_duplicate(bot: commands.Bot, message: discord.Message):
        if bot.get_cog("Ai") is not None:
            return None
        return await current(bot, message)

    mention_help_without_duplicate._sentrix_compact_home_guard = True
    mention_help_without_duplicate._sentrix_original = current
    common_command_names._mention_help = mention_help_without_duplicate
    _MENTION_PATCHED = True


def _disable_separate_language_join_prompt() -> None:
    """Le choix de langue reste intégré au nouvel accueil, sans second message."""
    global _LANGUAGE_JOIN_PATCHED
    if _LANGUAGE_JOIN_PATCHED:
        return

    from . import language_runtime

    current = getattr(language_runtime, "_send_initial_language_prompt", None)
    if current is None:
        return
    if getattr(current, "_sentrix_join_prompt_disabled", False):
        _LANGUAGE_JOIN_PATCHED = True
        return

    async def no_separate_join_prompt(bot: commands.Bot, guild: discord.Guild):
        del bot, guild
        return None

    no_separate_join_prompt._sentrix_join_prompt_disabled = True
    no_separate_join_prompt._sentrix_original = current
    language_runtime._send_initial_language_prompt = no_separate_join_prompt
    _LANGUAGE_JOIN_PATCHED = True


async def _ensure_create_sentrix(bot: commands.Bot) -> None:
    """Installe/répare le routeur canonique ``+create``.

    L'ancienne V3 pouvait rester enregistrée sous le même nom de Cog et reprendre
    ``+create sentrix``. Le routeur sait retirer proprement cette ancienne racine avant de
    remettre ``sentrix`` et ``server`` sous un seul groupe.
    """
    from .create_command_router import install as install_create_router

    await install_create_router(bot)


async def install(bot: commands.Bot, extension_name: str = "") -> None:
    del extension_name
    _patch_error_dispatch()
    _patch_plain_response_install()
    _apply_error_context_transport()
    _patch_duplicate_mention()
    _disable_separate_language_join_prompt()
    await _ensure_create_sentrix(bot)


__all__ = ["install"]
