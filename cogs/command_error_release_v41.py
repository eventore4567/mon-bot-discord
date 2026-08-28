"""Dernière couche runtime : libération slash, renderer final et erreurs préfixées uniques."""
from __future__ import annotations

import inspect
import logging

import discord
from discord.ext import commands

from .command_hardening_v41 import release_slash
from .runtime_consistency_v57 import install as install_runtime_consistency_v57
from .setup_v2_runtime import install as install_setup_v2_runtime

logger = logging.getLogger("bot.command-error-release-v41")


def _force_final_renderer() -> None:
    """Réapplique V6 après toutes les anciennes couches visuelles."""
    from utils import embeds as sentrix_embeds
    from utils import wide_compact_v6 as v6

    sentrix_embeds._base = v6._base
    sentrix_embeds.add_fields = v6.add_fields
    sentrix_embeds.enrich_ping = v6.enrich_ping
    sentrix_embeds.style_existing = v6.style_existing


def _listener_identities(listener) -> set[tuple[str, str]]:
    """Retourne les identités du listener et de ses wrappers éventuels.

    Plusieurs couches SentriX utilisent functools.wraps / méthodes liées. La libération
    de concurrence ne doit jamais être supprimée simplement parce qu'elle est enveloppée.
    """
    identities: set[tuple[str, str]] = set()
    current = listener
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        function = getattr(current, "__func__", current)
        identities.add((
            str(getattr(function, "__module__", "") or ""),
            str(getattr(function, "__name__", "") or ""),
        ))
        next_obj = (
            getattr(function, "__wrapped__", None)
            or getattr(function, "_sentrix_previous", None)
            or getattr(function, "_sentrix_original", None)
        )
        current = next_obj
    return identities


def _dedupe_prefix_error_listeners(bot: commands.Bot) -> int:
    """Supprime les anciens responders, jamais les observers/libérateurs sûrs."""
    listeners = list(getattr(bot, "extra_events", {}).get("on_command_error", ()) or ())
    if not listeners:
        return 0

    kept = []
    removed = 0
    for listener in listeners:
        identities = _listener_identities(listener)
        safe_observer = any(
            (
                module.endswith("command_response_guard")
                and name == "observe_prefix_command_error"
            )
            or (
                module.endswith("production_phase_runtime")
                and name == "on_command_error"
            )
            or name == "prefix_failed"
            for module, name in identities
        )
        if safe_observer:
            kept.append(listener)
        else:
            removed += 1

    if kept:
        bot.extra_events["on_command_error"] = kept
    else:
        bot.extra_events.pop("on_command_error", None)
    return removed


def install(bot: commands.Bot) -> None:
    """Installe les derniers garde-fous sans modifier la logique métier des commandes."""
    _force_final_renderer()
    removed = _dedupe_prefix_error_listeners(bot)
    if removed:
        logger.info("Erreurs préfixées : %s ancien(s) listener(s) concurrent(s) retiré(s).", removed)

    # V57 d'abord, puis V2 comme dernière source de vérité +/slash.
    install_runtime_consistency_v57(bot)
    install_setup_v2_runtime(bot)

    current = bot.tree.on_error
    if getattr(current, "_sentrix_v41_release", False):
        logger.info("Renderer V6 final réappliqué ; erreurs préfixées dédupliquées.")
        return

    async def error_with_release(
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ):
        release_slash(interaction)
        result = current(interaction, error)
        if inspect.isawaitable(result):
            return await result
        return result

    error_with_release._sentrix_v41_release = True
    error_with_release._sentrix_previous = current
    bot.tree.on_error = error_with_release
    logger.info("V41 : renderer V6 final, erreur préfixée unique et verrou slash libéré.")