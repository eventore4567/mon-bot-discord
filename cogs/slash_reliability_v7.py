"""Fiabilite des interactions slash SentriX.

Cette couche ne gere ni le catalogue ni les permissions. Elle ajoute seulement :
- un auto-defer pour les commandes slash lentes ;
- la fermeture des placeholders de defer restes vides apres une commande terminee ;
- une telemetrie minimale pour verifier le chemin reel en production.
"""
from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord.ext import commands

from . import permission_guard

logger = logging.getLogger("bot.slash-reliability-v7")
_ROOT_ALIASES = {"nick": "nickname"}
_DEFER_DELAY_SECONDS = 1.8
_AUTO_DEFER_TTL_SECONDS = 300.0


def _runtime_state(bot: commands.Bot) -> dict:
    state = getattr(bot, "slash_reliability_v7_state", None)
    if not isinstance(state, dict):
        state = {
            "installed_at": None,
            "watchdog_listener_registered": False,
            "completion_guard_registered": False,
            "last_interaction_seen_at": None,
            "last_completion_at": None,
            "last_response_type": None,
            "last_response_done": None,
            "last_original_had_payload": None,
            "last_result": None,
            "last_error": None,
        }
        bot.slash_reliability_v7_state = state
    return state


def _mark_state(bot: commands.Bot, **values) -> None:
    _runtime_state(bot).update(values)


def _response_type_name(interaction: discord.Interaction) -> str | None:
    response_type = getattr(interaction.response, "type", None)
    return getattr(response_type, "name", None) or (str(response_type) if response_type is not None else None)


def _auto_deferred(bot: commands.Bot) -> dict[int, float]:
    tracker = getattr(bot, "_sentrix_auto_deferred_slash", None)
    if not isinstance(tracker, dict):
        tracker = {}
        bot._sentrix_auto_deferred_slash = tracker
    return tracker


def _prune_auto_deferred(bot: commands.Bot) -> None:
    tracker = _auto_deferred(bot)
    if not tracker:
        return
    now = time.monotonic()
    stale = [interaction_id for interaction_id, stamp in tracker.items() if now - stamp > _AUTO_DEFER_TTL_SECONDS]
    for interaction_id in stale:
        tracker.pop(interaction_id, None)


def _mark_auto_deferred(interaction: discord.Interaction) -> None:
    bot = interaction.client
    if not isinstance(bot, commands.Bot):
        return
    tracker = _auto_deferred(bot)
    tracker[int(interaction.id)] = time.monotonic()
    if len(tracker) > 5000:
        _prune_auto_deferred(bot)


def _take_auto_deferred(interaction: discord.Interaction) -> bool:
    bot = interaction.client
    if not isinstance(bot, commands.Bot):
        return False
    return _auto_deferred(bot).pop(int(interaction.id), None) is not None


def _original_response_has_payload(message: discord.InteractionMessage) -> bool:
    """Vrai si la reponse originale contient deja un vrai resultat de commande."""
    return bool(
        (getattr(message, "content", "") or "").strip()
        or getattr(message, "embeds", None)
        or getattr(message, "attachments", None)
        or getattr(message, "components", None)
        or getattr(message, "stickers", None)
        or getattr(message, "poll", None)
    )


def _interaction_is_deferred(interaction: discord.Interaction) -> bool:
    """Couvre le defer watchdog et les defer faits directement par une commande."""
    response_type = getattr(interaction.response, "type", None)
    return response_type in {
        discord.InteractionResponseType.deferred_channel_message,
        discord.InteractionResponseType.deferred_message_update,
    }


async def _settle_deferred(interaction: discord.Interaction, command_name: str) -> bool:
    """Ferme un placeholder slash differe reste vide apres succes.

    Si la commande a deja remplace le defer par du texte, un embed, un fichier ou un
    composant, cette reponse est conservee telle quelle.
    """
    bot = interaction.client
    tracked_by_watchdog = _take_auto_deferred(interaction)
    response_done = bool(interaction.response.is_done())
    if isinstance(bot, commands.Bot):
        _mark_state(
            bot,
            last_completion_at=int(time.time()),
            last_response_type=_response_type_name(interaction),
            last_response_done=response_done,
            last_original_had_payload=None,
            last_result="completion_seen",
            last_error=None,
        )

    if not response_done:
        if isinstance(bot, commands.Bot):
            _mark_state(bot, last_result="response_not_done")
        return tracked_by_watchdog

    if not tracked_by_watchdog and not _interaction_is_deferred(interaction):
        if isinstance(bot, commands.Bot):
            _mark_state(bot, last_result="not_deferred")
        return False

    try:
        original = await interaction.original_response()
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, discord.ClientException) as exc:
        if isinstance(bot, commands.Bot):
            _mark_state(bot, last_result="original_unavailable", last_error=type(exc).__name__)
        return tracked_by_watchdog

    has_payload = _original_response_has_payload(original)
    if isinstance(bot, commands.Bot):
        _mark_state(bot, last_original_had_payload=has_payload)
    if has_payload:
        if isinstance(bot, commands.Bot):
            _mark_state(bot, last_result="payload_present")
        return tracked_by_watchdog

    try:
        await interaction.edit_original_response(
            content="Commande exécutée avec succès.",
            embeds=[],
            attachments=[],
            view=None,
        )
        if isinstance(bot, commands.Bot):
            _mark_state(bot, last_result="settled", last_error=None)
        logger.info(
            "Defer slash resolu apres completion : /%s (user=%s, guild=%s, watchdog=%s).",
            command_name,
            getattr(interaction.user, "id", None),
            interaction.guild_id,
            tracked_by_watchdog,
        )
    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
        if isinstance(bot, commands.Bot):
            _mark_state(bot, last_result="edit_failed", last_error=type(exc).__name__)
        logger.debug("Impossible de cloturer le defer pour /%s.", command_name, exc_info=True)
        return tracked_by_watchdog
    return True


def _install_canonical_root_mapping() -> None:
    current = permission_guard.interaction_root_name
    if getattr(current, "_sentrix_slash_v7_canonical", False):
        return

    def canonical_root(interaction: discord.Interaction) -> str:
        root = current(interaction)
        return _ROOT_ALIASES.get(root, root)

    canonical_root._sentrix_slash_v7_canonical = True
    permission_guard.interaction_root_name = canonical_root


async def _defer_watchdog(interaction: discord.Interaction) -> None:
    await asyncio.sleep(_DEFER_DELAY_SECONDS)
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)
            _mark_auto_deferred(interaction)
    except (discord.InteractionResponded, discord.NotFound):
        return
    except discord.HTTPException:
        logger.debug("Auto-defer slash impossible.", exc_info=True)


def _install_watchdog_listener(bot: commands.Bot) -> None:
    """Observe les interactions sans remplacer tree.interaction_check.

    Le garde central de permissions/blacklist reste donc exactement celui installe par
    permission_guard.py ; V7 ne fait que lancer son watchdog en parallele.
    """
    if getattr(bot, "_sentrix_slash_watchdog_listener_registered", False):
        return

    async def watch_interaction(interaction: discord.Interaction) -> None:
        if interaction.type != discord.InteractionType.application_command:
            return
        _mark_state(bot, last_interaction_seen_at=int(time.time()))
        asyncio.create_task(_defer_watchdog(interaction))

    bot.add_listener(watch_interaction, "on_interaction")
    bot._sentrix_slash_watchdog_listener = watch_interaction
    bot._sentrix_slash_watchdog_listener_registered = True
    _mark_state(bot, watchdog_listener_registered=True)


def _install_completion_guard(bot: commands.Bot) -> None:
    """Termine les placeholders defer apres succes, natifs comme hybrides."""
    if getattr(bot, "_sentrix_slash_auto_defer_completion_guard", False):
        return

    async def settle_app_command(
        interaction: discord.Interaction,
        command: discord.app_commands.Command | discord.app_commands.ContextMenu,
    ) -> None:
        name = str(getattr(command, "qualified_name", getattr(command, "name", "commande")))
        await _settle_deferred(interaction, name)

    async def settle_hybrid_command(ctx: commands.Context) -> None:
        interaction = getattr(ctx, "interaction", None)
        if interaction is None or interaction.type != discord.InteractionType.application_command:
            return
        command = getattr(ctx, "command", None)
        name = str(getattr(command, "qualified_name", getattr(command, "name", "commande")))
        await _settle_deferred(interaction, name)

    bot.add_listener(settle_app_command, "on_app_command_completion")
    bot.add_listener(settle_hybrid_command, "on_command_completion")
    bot._sentrix_slash_auto_defer_completion_guard = True
    _mark_state(bot, completion_guard_registered=True)


def install(bot: commands.Bot) -> None:
    """Installe uniquement la fiabilite interactionnelle, sans toucher au catalogue."""
    if getattr(bot, "_sentrix_slash_reliability_v7_installed", False):
        return
    _runtime_state(bot)
    _install_canonical_root_mapping()
    _install_watchdog_listener(bot)
    _install_completion_guard(bot)
    bot._sentrix_slash_reliability_v7_installed = True
    _mark_state(bot, installed_at=int(time.time()), last_error=None)
    logger.info("Slash Reliability V7 actif : watchdog + completion, garde permissions intacte.")


async def setup(bot: commands.Bot) -> None:
    install(bot)
