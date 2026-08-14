"""Fiabilite des commandes slash : garde unique, auto-defer et sync finale."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import discord
from discord.ext import commands

from . import command_catalog_cleanup, command_hybrid_slash_restore_v3, permission_guard, slash_command_budget

logger = logging.getLogger("bot.slash-reliability-v7")
_ROOT_ALIASES = {"nick": "nickname"}
_DEFER_DELAY_SECONDS = 1.8
_AUTO_DEFER_TTL_SECONDS = 300.0


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
    """Vrai si une commande a déjà remplacé le placeholder de defer par un vrai résultat."""
    return bool(
        (getattr(message, "content", "") or "").strip()
        or getattr(message, "embeds", None)
        or getattr(message, "attachments", None)
        or getattr(message, "components", None)
        or getattr(message, "stickers", None)
        or getattr(message, "poll", None)
    )


def _interaction_is_deferred(interaction: discord.Interaction) -> bool:
    """Détecte aussi les defer créés directement par une commande, pas seulement le watchdog."""
    response_type = getattr(interaction.response, "type", None)
    return response_type in {
        discord.InteractionResponseType.deferred_channel_message,
        discord.InteractionResponseType.deferred_message_update,
    }


async def _settle_auto_deferred(interaction: discord.Interaction, command_name: str) -> bool:
    """Ferme tout placeholder slash différé resté vide après une commande réussie.

    Le premier correctif ne suivait que les defer créés par notre watchdog. Certaines commandes
    hybrides ou natives appellent cependant ``defer()`` elles-mêmes. Elles pouvaient donc finir
    leur vraie action tout en laissant Discord afficher « SentriX réfléchit… ».

    Cette version couvre les deux cas : defer SentriX et defer interne à la commande. Une vraie
    réponse existante (texte, embed, fichier, composant, etc.) est toujours conservée intacte.
    """
    tracked_by_watchdog = _take_auto_deferred(interaction)

    if not interaction.response.is_done():
        return tracked_by_watchdog
    if not tracked_by_watchdog and not _interaction_is_deferred(interaction):
        return False

    try:
        original = await interaction.original_response()
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, discord.ClientException):
        # Réponse originale supprimée/inaccessible : aucun placeholder visible à nettoyer.
        return tracked_by_watchdog

    if _original_response_has_payload(original):
        return tracked_by_watchdog

    try:
        await interaction.edit_original_response(
            content="Commande exécutée avec succès.",
            embeds=[],
            attachments=[],
            view=None,
        )
        logger.info(
            "Defer slash résolu après completion : /%s (user=%s, guild=%s, watchdog=%s).",
            command_name,
            getattr(interaction.user, "id", None),
            interaction.guild_id,
            tracked_by_watchdog,
        )
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        logger.debug("Impossible de clôturer le defer pour /%s.", command_name, exc_info=True)
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


def _install_single_interaction_guard(bot: commands.Bot) -> None:
    tree = bot.tree
    if getattr(tree, "_sentrix_slash_reliability_v7_guard", False):
        return

    async def reliable_interaction_check(interaction: discord.Interaction) -> bool:
        if interaction.type != discord.InteractionType.application_command:
            return True
        asyncio.create_task(_defer_watchdog(interaction))
        decision = await permission_guard.evaluate_interaction_access(bot, interaction)
        if decision.allowed:
            return True
        await permission_guard._send_interaction_denial(interaction, decision)
        return False

    tree.interaction_check = reliable_interaction_check
    tree._sentrix_slash_reliability_v7_guard = True
    tree._sentrix_interaction_policy_v2 = True


def _install_auto_defer_completion_guard(bot: commands.Bot) -> None:
    """Termine les placeholders defer après succès, y compris les defer internes/hybrides."""
    if getattr(bot, "_sentrix_slash_auto_defer_completion_guard", False):
        return

    async def settle_app_command(
        interaction: discord.Interaction,
        command: discord.app_commands.Command | discord.app_commands.ContextMenu,
    ) -> None:
        name = str(getattr(command, "qualified_name", getattr(command, "name", "commande")))
        await _settle_auto_deferred(interaction, name)

    async def settle_hybrid_command(ctx: commands.Context) -> None:
        interaction = getattr(ctx, "interaction", None)
        if interaction is None or interaction.type != discord.InteractionType.application_command:
            return
        command = getattr(ctx, "command", None)
        name = str(getattr(command, "qualified_name", getattr(command, "name", "commande")))
        await _settle_auto_deferred(interaction, name)

    bot.add_listener(settle_app_command, "on_app_command_completion")
    bot.add_listener(settle_hybrid_command, "on_command_completion")
    bot._sentrix_slash_auto_defer_completion_guard = True


def _expected_slash_roots() -> set[str]:
    return set(command_catalog_cleanup.normal_direct_commands())


def _actual_slash_roots(bot: commands.Bot) -> set[str]:
    return {str(command.name).casefold() for command in bot.tree.get_commands()}


def _rebuild_slash_catalog(bot: commands.Bot) -> tuple[set[str], set[str]]:
    command_catalog_cleanup.finalize(bot)
    command_hybrid_slash_restore_v3.restore(bot)
    slash_command_budget.finalize(bot)
    expected = _expected_slash_roots()
    actual = _actual_slash_roots(bot)
    missing = expected - actual
    extra = actual - expected
    if missing or extra:
        command_hybrid_slash_restore_v3.restore(bot)
        slash_command_budget.finalize(bot)
        actual = _actual_slash_roots(bot)
        missing = expected - actual
        extra = actual - expected
    return missing, extra


def _install_reliable_sync(bot: commands.Bot) -> None:
    tree = bot.tree
    if getattr(tree, "_sentrix_slash_reliability_v7_sync", False):
        return
    original_sync = tree.sync

    async def reliable_sync(*args: Any, **kwargs: Any):
        missing, extra = _rebuild_slash_catalog(bot)
        if missing or extra:
            logger.error("Catalogue slash invalide avant sync: missing=%s extra=%s", sorted(missing), sorted(extra))
            raise RuntimeError(f"Catalogue slash incomplet: missing={sorted(missing)} extra={sorted(extra)}")
        result = await original_sync(*args, **kwargs)
        logger.info("Synchronisation slash reussie: %s commandes globales.", len(_expected_slash_roots()))
        return result

    tree.sync = reliable_sync
    tree._sentrix_slash_reliability_v7_sync = True


def install(bot: commands.Bot) -> None:
    _install_canonical_root_mapping()
    _install_single_interaction_guard(bot)
    _install_auto_defer_completion_guard(bot)
    _install_reliable_sync(bot)
    missing, extra = _rebuild_slash_catalog(bot)
    logger.info("Slash Reliability V7 actif (missing=%s extra=%s).", sorted(missing), sorted(extra))


async def _install_production_v9(bot: commands.Bot) -> None:
    """Charge les améliorations runtime V9 après la stabilisation du catalogue slash."""
    from . import ai_context_v9, game_seasons_v9, moderation_advisor_v9, production_observability_v9

    await production_observability_v9.setup(bot)
    await ai_context_v9.setup(bot)
    await game_seasons_v9.setup(bot)
    await moderation_advisor_v9.setup(bot)


async def _install_bot_v10(bot: commands.Bot) -> None:
    """Charge V10 après V9 afin de réutiliser ses moteurs sans toucher au catalogue slash."""
    from . import bot_v10

    if bot.get_cog("BotV10") is None:
        await bot_v10.setup(bot)


async def setup(bot: commands.Bot) -> None:
    install(bot)
    await _install_production_v9(bot)
    await _install_bot_v10(bot)
