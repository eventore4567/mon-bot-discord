"""Correctifs finaux de cohérence runtime SentriX.

Cette couche reste volontairement ciblée :
- la matrice globale de permissions doit accepter le rôle staff déjà configuré,
  comme les checks locaux historiques le font ;
- les refus préfixés doivent afficher la vraie raison au lieu d'un refus générique ;
- un log activé dont le salon dédié est devenu invalide peut retomber sur le salon
  général historique, sans réactiver un type de log désactivé explicitement.
"""
from __future__ import annotations

import inspect
import logging
from types import MethodType
from typing import Any

import discord
from discord.ext import commands

from utils import embeds, log_service
from utils import sentrix_panels as panels
from utils.checks import BotBlacklistedError, BotPermissionError

from . import permission_guard

logger = logging.getLogger("bot.runtime-consistency-v57")


def _config_value(config_row: Any, key: str):
    if config_row is None:
        return None
    try:
        return config_row[key]
    except (KeyError, IndexError, TypeError):
        return None


async def _has_configured_staff_role(bot: commands.Bot, guild: Any, author: Any) -> bool:
    """Utilise exactement le rôle ``setmodrole`` déjà stocké dans guild_config."""
    guild_id = getattr(guild, "id", None)
    if guild_id is None or author is None:
        return False
    try:
        conf = await bot.db.get_guild_config(int(guild_id))
    except Exception:
        logger.exception("Lecture du rôle staff impossible pour guild=%s", guild_id)
        return False

    role_id = _config_value(conf, "mod_role")
    if not role_id:
        return False
    try:
        wanted = int(role_id)
    except (TypeError, ValueError):
        return False
    return any(int(getattr(role, "id", 0) or 0) == wanted for role in getattr(author, "roles", ()) or ())


def _install_permission_consistency(bot: commands.Bot) -> None:
    """Neutralise : owner serveur et role staff configure sont dans la matrice.

    Ce wrapper accordait un bypass owner-serveur APRES coup, ce qui pouvait
    annuler un refus explicite enregistre dans Setup.
    """
    return


def _install_prefix_error_detail(bot: commands.Bot) -> None:
    current = getattr(bot, "on_command_error", None)
    if not callable(current) or getattr(current, "_sentrix_v57_error_detail", False):
        return

    async def detailed_on_command_error(
        self: commands.Bot,
        ctx: commands.Context,
        error: commands.CommandError,
    ):
        base = getattr(error, "original", error)
        if isinstance(base, BotPermissionError):
            await panels.envoyer(ctx, panels.depuis_embed(embeds.error(base.message, title='Permission insuffisante')))
            return
        if isinstance(base, BotBlacklistedError):
            await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f"Vous n'êtes pas autorisé à utiliser SentriX.\n\nRaison : {base.reason}", title='Accès refusé')))
            return

        result = current(ctx, error)
        if inspect.isawaitable(result):
            return await result
        return result

    detailed_on_command_error._sentrix_v57_error_detail = True
    detailed_on_command_error._sentrix_previous = current
    bot.on_command_error = MethodType(detailed_on_command_error, bot)
    logger.info("V57 : raisons de refus préfixées détaillées restaurées.")


# Les durées naturelles de +mute (« 10 minutes ») sont normalisées dans
# cogs/moderation.py::Moderation._normalise_prefix_duration.


def _valid_log_channel(guild: discord.Guild, channel_id: int | None) -> bool:
    ok, _reason = log_service.validate_channel(guild, channel_id)
    return bool(ok)


def _install_log_fallback() -> None:
    """Ne remplace plus log_service.get_log_setting.

    Ce repli relisait les colonnes legacy de guild_config, y compris le salon GLOBAL
    log_channel, des que le salon d'une categorie devenait invalide. N'importe quelle
    categorie basculait donc dans le salon general : un bannissement finissait dans le
    meme salon qu'un message supprime, alors que chaque categorie a son propre salon.

    log_config est la seule source de verite. Quand un salon disparait, la validation le
    signale, et live_log_delivery_v5 retrouve un salon par son nom DANS la meme categorie
    au lieu de traverser les categories.
    """
    return None


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_runtime_consistency_v57", False):
        return
    _install_permission_consistency(bot)
    _install_prefix_error_detail(bot)
    _install_log_fallback()
    bot._sentrix_runtime_consistency_v57 = True
    logger.info("V57 : cohérence permissions/erreurs/logs active.")


__all__ = ["install"]
