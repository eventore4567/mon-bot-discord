"""Dernière couche runtime : libération slash, renderer final et erreurs préfixées uniques."""
from __future__ import annotations

import inspect
import logging

import discord
from discord.ext import commands

from .command_hardening_v41 import release_slash

logger = logging.getLogger("bot.command-error-release-v41")


def _force_final_renderer() -> None:
    """Réapplique V6 après toutes les anciennes couches visuelles.

    ``utils`` importe V6 très tôt au démarrage. Plusieurs couches historiques chargées
    ensuite peuvent donc réécrire ``utils.embeds.style_existing`` et faire réapparaître
    l'ancien +ping (bannière + double barre). Ce patch final ne crée aucun transport : il
    remet simplement les quatre fonctions visuelles V6 en dernier.
    """
    from utils import embeds as sentrix_embeds
    from utils import wide_compact_v6 as v6

    sentrix_embeds._base = v6._base
    sentrix_embeds.add_fields = v6.add_fields
    sentrix_embeds.enrich_ping = v6.enrich_ping
    sentrix_embeds.style_existing = v6.style_existing


def _dedupe_prefix_error_listeners(bot: commands.Bot) -> int:
    """Supprime les anciens listeners qui répondent encore aux erreurs.

    Le message utilisateur appartient exclusivement à ``error_experience_v3`` via
    ``bot.on_command_error``. On conserve uniquement les deux listeners connus qui ne
    répondent jamais dans Discord : observabilité et métriques production.
    """
    listeners = list(getattr(bot, "extra_events", {}).get("on_command_error", ()) or ())
    if not listeners:
        return 0

    kept = []
    removed = 0
    for listener in listeners:
        function = getattr(listener, "__func__", listener)
        module = str(getattr(function, "__module__", "") or "")
        name = str(getattr(function, "__name__", "") or "")
        safe_observer = (
            module.endswith("command_response_guard")
            and name == "observe_prefix_command_error"
        ) or (
            module.endswith("production_phase_runtime")
            and name == "on_command_error"
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
    """Installe les derniers garde-fous sans modifier la logique des commandes."""
    _force_final_renderer()
    removed = _dedupe_prefix_error_listeners(bot)
    if removed:
        logger.info("Erreurs préfixées : %s ancien(s) listener(s) concurrent(s) retiré(s).", removed)

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
