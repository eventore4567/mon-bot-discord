"""Correctifs finaux de cohérence runtime SentriX.

Cette couche reste volontairement ciblée :
- la matrice globale de permissions doit accepter le rôle staff déjà configuré,
  comme les checks locaux historiques le font ;
- les refus préfixés doivent afficher la vraie raison au lieu d'un refus générique ;
- ``+mute @membre 10 minutes`` doit être compris comme ``10m`` ;
- un log activé dont le salon dédié est devenu invalide peut retomber sur le salon
  général historique, sans réactiver un type de log désactivé explicitement.
"""
from __future__ import annotations

import functools
import inspect
import logging
from types import MethodType
from typing import Any

import discord
from discord.ext import commands

from utils import embeds, log_service
from utils.checks import BotBlacklistedError, BotPermissionError
from utils.helpers import parse_duration

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
    if getattr(permission_guard.evaluate_command_access, "_sentrix_v57_consistency", False):
        return

    original = permission_guard.evaluate_command_access

    async def evaluate_with_consistency(
        target_bot: commands.Bot,
        *,
        command_name: str,
        author: Any,
        guild: Any,
    ) -> permission_guard.AccessDecision:
        decision = await original(
            target_bot,
            command_name=command_name,
            author=author,
            guild=guild,
        )
        if decision.allowed:
            return decision

        # Le propriétaire DU SERVEUR a toujours le niveau administrateur sur son propre
        # serveur. Cela ne donne jamais accès aux commandes owner-only globales SentriX.
        guild_owner_id = getattr(guild, "owner_id", None)
        author_id = getattr(author, "id", None)
        if (
            decision.policy != "owner"
            and guild_owner_id is not None
            and author_id is not None
            and int(author_id) == int(guild_owner_id)
        ):
            return permission_guard.AccessDecision(True, policy="guild-owner-bypass")

        # Le vieux verrou de main.py et les checks locaux utilisent déjà setmodrole pour
        # les commandes à permission Discord. La nouvelle matrice globale l'avait oublié,
        # ce qui créait un refus contradictoire avant même l'exécution de la commande.
        if decision.policy.startswith("discord:") and await _has_configured_staff_role(
            target_bot, guild, author
        ):
            return permission_guard.AccessDecision(True, policy="configured-staff-role")

        return decision

    evaluate_with_consistency._sentrix_v57_consistency = True
    evaluate_with_consistency._sentrix_previous = original
    permission_guard.evaluate_command_access = evaluate_with_consistency
    logger.info("V57 : permissions globales alignées sur propriétaire serveur + rôle staff configuré.")


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
            await ctx.send(embed=embeds.error(base.message, title="Permission insuffisante"))
            return
        if isinstance(base, BotBlacklistedError):
            await ctx.send(
                embed=embeds.error(
                    f"Vous n'êtes pas autorisé à utiliser SentriX.\n\nRaison : {base.reason}",
                    title="Accès refusé",
                )
            )
            return

        result = current(ctx, error)
        if inspect.isawaitable(result):
            return await result
        return result

    detailed_on_command_error._sentrix_v57_error_detail = True
    detailed_on_command_error._sentrix_previous = current
    bot.on_command_error = MethodType(detailed_on_command_error, bot)
    logger.info("V57 : raisons de refus préfixées détaillées restaurées.")


def _normalise_prefix_duration(duree: str, raison: str) -> tuple[str, str]:
    """Réassemble les durées françaises que le parseur de commandes coupe en 2 mots."""
    raw_duration = str(duree or "").strip()
    raw_reason = str(raison or "").strip()
    if parse_duration(raw_duration) is not None or not raw_reason:
        return raw_duration, raw_reason or "Aucune raison"

    first, *rest = raw_reason.split(maxsplit=1)
    candidate = f"{raw_duration} {first}".strip()
    if parse_duration(candidate) is None:
        return raw_duration, raw_reason or "Aucune raison"
    return candidate, rest[0] if rest else "Aucune raison"


def _install_mute_duration_compat(bot: commands.Bot) -> None:
    command = bot.get_command("mute")
    if command is None:
        logger.warning("V57 : commande +mute introuvable, compatibilité durée non installée.")
        return
    original = getattr(command, "callback", None)
    if not callable(original) or getattr(original, "_sentrix_v57_duration", False):
        return

    @functools.wraps(original)
    async def mute_with_human_duration(cog, ctx, membre, duree, *, raison="Aucune raison"):
        if getattr(ctx, "interaction", None) is None:
            duree, raison = _normalise_prefix_duration(duree, raison)
        result = original(cog, ctx, membre, duree, raison=raison)
        if inspect.isawaitable(result):
            return await result
        return result

    mute_with_human_duration._sentrix_v57_duration = True
    mute_with_human_duration._sentrix_previous = original
    command.callback = mute_with_human_duration
    logger.info("V57 : +mute accepte aussi les durées naturelles comme « 10 minutes ».")


def _valid_log_channel(guild: discord.Guild, channel_id: int | None) -> bool:
    ok, _reason = log_service.validate_channel(guild, channel_id)
    return bool(ok)


def _install_log_fallback() -> None:
    current = log_service.get_log_setting
    if getattr(current, "_sentrix_v57_fallback", False):
        return

    async def get_log_setting_with_fallback(bot, guild_id: int, log_type: str) -> dict:
        setting = await current(bot, guild_id, log_type)
        # Une désactivation explicite doit rester une désactivation : aucun fallback.
        if not setting.get("enabled"):
            return setting

        guild = bot.get_guild(int(guild_id)) if hasattr(bot, "get_guild") else None
        if guild is None or _valid_log_channel(guild, setting.get("channel_id")):
            return setting

        try:
            conf = await bot.db.get_guild_config(int(guild_id))
        except Exception:
            logger.exception("V57 : lecture fallback logs impossible pour guild=%s", guild_id)
            return setting
        if not conf:
            return setting

        meta = log_service.LOG_TYPES.get(log_type, {})
        legacy_column = meta.get("legacy_column")
        candidates: list[int] = []
        for key in (legacy_column, "log_channel"):
            if not key:
                continue
            value = _config_value(conf, str(key))
            if not value:
                continue
            try:
                channel_id = int(value)
            except (TypeError, ValueError):
                continue
            if channel_id not in candidates:
                candidates.append(channel_id)

        broken_id = setting.get("channel_id")
        for candidate in candidates:
            if candidate == broken_id:
                continue
            if not _valid_log_channel(guild, candidate):
                continue
            repaired = dict(setting)
            repaired["channel_id"] = candidate
            logger.warning(
                "V57 : log %s guild=%s redirigé vers le salon général valide %s "
                "car le salon configuré %s est inutilisable.",
                log_type,
                guild_id,
                candidate,
                broken_id,
            )
            return repaired
        return setting

    get_log_setting_with_fallback._sentrix_v57_fallback = True
    get_log_setting_with_fallback._sentrix_previous = current
    log_service.get_log_setting = get_log_setting_with_fallback
    logger.info("V57 : fallback des logs activés vers le salon général valide installé.")


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_runtime_consistency_v57", False):
        return
    _install_permission_consistency(bot)
    _install_prefix_error_detail(bot)
    _install_mute_duration_compat(bot)
    _install_log_fallback()
    bot._sentrix_runtime_consistency_v57 = True
    logger.info("V57 : cohérence permissions/erreurs/durées/logs active.")


__all__ = ["install", "_normalise_prefix_duration"]
