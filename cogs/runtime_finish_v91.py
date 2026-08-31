"""V91 — +create manox doit réellement terminer toute la structure de référence.

Le preset V89 est déjà idempotent, mais V91 retire le premier passage historique fragile :
la commande effectue directement plusieurs passes de réparation, vérifie chaque catégorie
et chaque salon attendu, puis configure SentriX uniquement sur la structure finale.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import discord
from discord.ext import commands

from . import runtime_finish_v84 as v84
from . import runtime_finish_v85 as v85
from . import runtime_finish_v89 as v89
from . import runtime_finish_v90 as v90

logger = logging.getLogger("bot.runtime-finish-v91")

MAX_STRUCTURE_PASSES = 4


def _expected_missing(guild: discord.Guild) -> list[str]:
    """Retourne les éléments du modèle qui ne sont pas encore à leur emplacement attendu."""
    missing: list[str] = []

    for kind, name in v84.ROOT_CHANNELS:
        if v85._find_channel_scoped(guild, name, kind, None) is None:
            missing.append(name)

    for category_name, _private, specs in v84.MANOX_STRUCTURE:
        category = discord.utils.get(guild.categories, name=category_name)
        if category is None:
            missing.append(category_name)
            # La catégorie absente implique déjà tous ses enfants : inutile de remplir
            # le rapport avec des dizaines de doublons.
            continue
        for kind, name, _user_limit in specs:
            if v85._find_channel_scoped(guild, name, kind, category) is None:
                missing.append(name)

    return missing


async def _complete_structure(
    guild: discord.Guild,
    author: discord.Member,
) -> tuple[dict[str, Any], dict[str, discord.CategoryChannel], int, int, list[str], list[str]]:
    channels: dict[str, Any] = {}
    categories: dict[str, discord.CategoryChannel] = {}
    created_channels = 0
    created_categories = 0
    warnings: list[str] = []

    for attempt in range(1, MAX_STRUCTURE_PASSES + 1):
        pass_channels, pass_categories, made_channels, made_categories, pass_warnings = (
            await v89._ensure_structure_resilient(guild, author)
        )
        channels.update(pass_channels)
        categories.update(pass_categories)
        created_channels += int(made_channels)
        created_categories += int(made_categories)
        warnings.extend(pass_warnings)

        missing = _expected_missing(guild)
        if not missing:
            break

        logger.warning(
            "Manox V91 : passe %s/%s incomplète guild=%s, reste=%s",
            attempt,
            MAX_STRUCTURE_PASSES,
            guild.id,
            ", ".join(missing[:20]),
        )
        if attempt < MAX_STRUCTURE_PASSES:
            # Laisse Discord propager les créations dans le cache avant la passe suivante.
            await asyncio.sleep(1.5)

    # Recharge les objets directement depuis Discord : une ressource créée durant une passe
    # précédente doit être utilisable pour la configuration même si son dictionnaire local
    # n'avait pas été rempli à cause d'une étape secondaire en erreur.
    for kind, name in v84.ROOT_CHANNELS:
        found = v85._find_channel_scoped(guild, name, kind, None)
        if found is not None:
            channels[name] = found

    for category_name, _private, specs in v84.MANOX_STRUCTURE:
        category = discord.utils.get(guild.categories, name=category_name)
        if category is None:
            continue
        categories[category_name] = category
        for kind, name, _user_limit in specs:
            found = v85._find_channel_scoped(guild, name, kind, category)
            if found is not None:
                channels[name] = found

    missing = _expected_missing(guild)
    return (
        channels,
        categories,
        created_channels,
        created_categories,
        list(dict.fromkeys(str(item) for item in warnings if item)),
        missing,
    )


async def build_manox_v91(
    bot: commands.Bot,
    guild: discord.Guild,
    author: discord.Member,
) -> dict[str, Any]:
    (
        channels,
        categories,
        made_channels,
        made_categories,
        warnings,
        missing,
    ) = await _complete_structure(guild, author)

    # La configuration intervient APRÈS les passes de structure. Ainsi une erreur sur un
    # règlement, un panel ou un log ne peut plus empêcher la création des salons suivants.
    logs_ready, log_warnings = await v89._configure_logs(bot, guild, channels)
    warnings.extend(log_warnings)

    ticket_ready, ticket_warnings = await v89._ensure_ticket_panel_on_support(
        bot,
        guild,
        author,
        channels,
        categories,
    )
    warnings.extend(ticket_warnings)

    warnings.extend(
        await v89._configure_welcome_levels_rules(bot, guild, author, channels)
    )

    security_ready, security_warnings = await v89._apply_security_best_effort(
        bot,
        guild,
        author,
    )
    warnings.extend(security_warnings)

    if missing:
        short = ", ".join(missing[:12])
        if len(missing) > 12:
            short += f" (+{len(missing) - 12})"
        warnings.append(f"structure manquante : {short}")

    warnings = list(dict.fromkeys(str(item) for item in warnings if item))
    return {
        "categories_created": made_categories,
        "categories_total": len(v84.MANOX_STRUCTURE),
        "channels_created": made_channels,
        "channels_total": len(v84.ROOT_CHANNELS)
        + sum(len(specs) for _name, _private, specs in v84.MANOX_STRUCTURE),
        "logs_ready": logs_ready,
        "ticket_ready": ticket_ready,
        "security_ready": security_ready,
        "structure_complete": not missing,
        "missing": missing,
        "warnings": warnings,
    }


def _patch_manox_final() -> None:
    current = v84.build_manox_server
    if getattr(current, "_sentrix_v91_complete", False):
        return

    build_manox_v91._sentrix_v91_complete = True
    build_manox_v91._sentrix_previous = current
    v84.build_manox_server = build_manox_v91
    logger.info(
        "+create manox V91 actif : structure vérifiée sur %s passes avant configuration.",
        MAX_STRUCTURE_PASSES,
    )


async def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_runtime_finish_v91", False):
        return
    await v90.install(bot)
    _patch_manox_final()
    bot._sentrix_runtime_finish_v91 = True
    logger.info("Runtime Finish V91 actif : preset manox complet et vérifié.")


__all__ = ["install", "build_manox_v91"]
