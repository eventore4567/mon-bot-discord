"""Corrige le cooldown global SentriX pour qu'il soit réellement par commande.

Historiquement ``BotAllInOne`` créait un seul ``CooldownMapping`` en ``BucketType.user``
puis l'utilisait dans un check global. Conséquence : trois commandes différentes lancées
rapidement consommaient le même quota et toutes les commandes semblaient ensuite en
cooldown. Cette couche remplace ce check par un mapping indépendant pour chaque commande.
"""
from __future__ import annotations

import logging
import time

from discord.ext import commands

import config
from database.db import PRIMARY_CREATOR_ID

logger = logging.getLogger("bot.cooldown-isolation")
_MARKER = "_sentrix_cooldown_isolation_v1"


def _command_key(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    if command is None:
        return "unknown"
    qualified = getattr(command, "qualified_name", None)
    if qualified:
        return str(qualified).casefold()
    return str(getattr(command, "name", "unknown")).casefold()


def _bucket_source(ctx: commands.Context):
    # BucketType.user ne lit que ``author.id``. Pour une commande préfixée, garder le
    # Message natif ; pour une hybrid/slash, Context expose lui aussi ``author``.
    message = getattr(ctx, "message", None)
    interaction = getattr(ctx, "interaction", None)
    return message if interaction is None and message is not None else ctx


def _state(bot: commands.Bot) -> dict:
    state = getattr(bot, "cooldown_isolation_state", None)
    if not isinstance(state, dict):
        state = {
            "installed": False,
            "installed_at": None,
            "mappings": {},
            "last_command": None,
            "last_user": None,
            "last_retry_after": None,
        }
        bot.cooldown_isolation_state = state
    return state


def install(bot: commands.Bot) -> None:
    """Remplace le check global partagé par un quota (utilisateur, commande)."""
    state = _state(bot)
    if state.get("installed") and getattr(bot, _MARKER, False):
        return

    # Retire le check historique déjà enregistré dans Bot.setup_hook(). ``remove_check``
    # compare les bound methods par self+fonction, donc récupérer à nouveau l'attribut est
    # suffisant pour retirer l'entrée présente dans ``bot._checks``.
    legacy_check = getattr(bot, "global_cooldown_check", None)
    if callable(legacy_check):
        try:
            bot.remove_check(legacy_check)
        except (ValueError, TypeError):
            pass

    # Ne jamais réutiliser le vieux mapping : il contient précisément l'état partagé qui
    # faisait croire que toutes les commandes étaient en cooldown.
    mappings: dict[str, commands.CooldownMapping] = {}
    state["mappings"] = mappings

    async def isolated_global_cooldown_check(ctx: commands.Context) -> bool:
        user_id = int(getattr(getattr(ctx, "author", None), "id", 0) or 0)
        if user_id == PRIMARY_CREATOR_ID or user_id in config.OWNER_IDS:
            return True
        if user_id and await bot.db.is_bot_creator(user_id):
            return True

        command_key = _command_key(ctx)
        mapping = mappings.get(command_key)
        if mapping is None:
            mapping = commands.CooldownMapping.from_cooldown(
                config.GLOBAL_COOLDOWN_RATE,
                config.GLOBAL_COOLDOWN_PER,
                commands.BucketType.user,
            )
            mappings[command_key] = mapping

        bucket = mapping.get_bucket(_bucket_source(ctx))
        retry_after = bucket.update_rate_limit()
        state.update(
            {
                "last_command": command_key,
                "last_user": user_id or None,
                "last_retry_after": float(retry_after) if retry_after else None,
            }
        )
        if retry_after:
            raise commands.CommandOnCooldown(
                bucket,
                retry_after,
                commands.BucketType.user,
            )
        return True

    isolated_global_cooldown_check._sentrix_cooldown_isolated = True
    bot.add_check(isolated_global_cooldown_check)
    bot._sentrix_isolated_global_cooldown_check = isolated_global_cooldown_check
    setattr(bot, _MARKER, True)

    state["installed"] = True
    state["installed_at"] = int(time.time())
    logger.warning(
        "Cooldown SentriX corrigé : quota isolé par utilisateur + commande (%s/%ss).",
        config.GLOBAL_COOLDOWN_RATE,
        config.GLOBAL_COOLDOWN_PER,
    )
