"""Fiabilite des commandes slash : garde unique, auto-defer et sync finale."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import discord
from discord.ext import commands

from . import command_catalog_cleanup, command_hybrid_slash_restore_v3, permission_guard, slash_command_budget

logger = logging.getLogger("bot.slash-reliability-v7")
_ROOT_ALIASES = {"nick": "nickname"}
_DEFER_DELAY_SECONDS = 1.8


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
