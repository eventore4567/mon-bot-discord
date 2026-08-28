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
    """Supprime uniquement les anciens listeners qui répondent encore aux erreurs.

    Le message utilisateur appartient exclusivement à ``error_experience_v3`` via
    ``bot.on_command_error``. Les listeners d'observabilité sont conservés, ainsi que
    ``command_hardening_v41.prefix_failed`` : ce dernier ne répond jamais dans Discord,
    il libère le verrou de concurrence d'une commande qui vient d'échouer.
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
        ) or (
            module.endswith("command_hardening_v41")
            and name == "prefix_failed"
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

    # Cette couche doit être posée même si le wrapper slash V41 l'était déjà : un reload
    # partiel ne doit pas laisser les permissions/logs/durées dans un état incohérent.
    install_runtime_consistency_v57(bot)
    # La V2 se pose après V57 afin que la matrice +/slash, les modules et la whitelist
    # deviennent la dernière source de vérité sans supprimer les protections existantes.
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