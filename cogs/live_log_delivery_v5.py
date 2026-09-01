"""V5 — livraison des logs auto-réparée au moment exact de l'événement.

Le démarrage ne doit plus être un prérequis pour les logs. Si SQLite a perdu la route,
si une ancienne migration n'a pas reconnu le nom du salon, ou si le channel_id est devenu
invalide, on retrouve un salon SentriX réellement présent dans Discord, on répare la DB,
puis on envoie CE MÊME événement sans attendre le prochain redémarrage.
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from typing import Any

import discord
from discord.ext import commands

from utils import log_service

logger = logging.getLogger("bot.live-log-delivery-v5")

# L'ordre est volontaire : le premier nom est le salon préféré quand plusieurs variantes
# historiques existent en même temps sur un serveur.
CHANNEL_ALIASES: dict[str, tuple[str, ...]] = {
    "messages": (
        "logs-messages", "logs-message",
    ),
    "members": (
        "logs-membre", "logs-membres", "logs-members",
    ),
    "roles": (
        "logs-roles", "logs-role", "logs-rôles", "logs-rôle",
    ),
    "voice": (
        "logs-vocal", "logs-vocaux", "logs-voice",
    ),
    "server": (
        "logs-serveur", "logs-salons", "logs-salon", "logs-dossiers",
        "logs-categories", "logs-catégories",
    ),
    "moderation": (
        "logs-moderation", "logs-modération", "logs-modo",
    ),
    "automod": (
        "logs-securite", "logs-sécurité", "automod", "logs-automod",
        "logs-protect-spam-logs", "protect-spam-logs", "raidprotect-logs",
        "logs-raidprotect",
    ),
    "tickets": (
        "logs-tickets", "ticket-logs", "tickets-logs",
    ),
}

_MARKER = "_sentrix_live_log_delivery_v5"
# Transport canonique en dessous de cette couche. Capture au moment de l'installation,
# pas a l'import : une capture a l'import dependait de l'ordre de chargement des cogs et
# pouvait court-circuiter une couche installee entre-temps.
_CANONICAL_SEND_LOG = None


def _canonical_send_log():
    """Le sender en dessous de V5. Repli sur log_service si rien n'a ete capture."""
    if _CANONICAL_SEND_LOG is not None:
        return _CANONICAL_SEND_LOG
    current = log_service.send_log
    return current if not getattr(current, _MARKER, False) else log_service.send_log


def _plain(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("・", "-").replace("_", "-").replace(" ", "-")
    text = re.sub(r"[^a-z0-9-]+", "-", text)
    return re.sub(r"-+", "-", text).strip("-")


def _aliases(log_type: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_plain(name) for name in CHANNEL_ALIASES.get(log_type, ())))


def _category_is_logs(channel: discord.TextChannel) -> bool:
    category = getattr(channel, "category", None)
    if category is None:
        return False
    name = _plain(getattr(category, "name", ""))
    return "logs" in name or ("sentrix" in name and "log" in name)


def _discover_channel(guild: discord.Guild, log_type: str) -> discord.TextChannel | None:
    aliases = _aliases(log_type)
    if not aliases:
        return None

    channels = list(getattr(guild, "text_channels", ()) or ())
    # 1) nom exact dans une catégorie de logs ; 2) nom exact ailleurs.
    # On suit l'ordre des alias pour conserver une route stable et prédictible.
    for require_logs_category in (True, False):
        for wanted in aliases:
            for channel in channels:
                if _plain(getattr(channel, "name", "")) != wanted:
                    continue
                if require_logs_category and not _category_is_logs(channel):
                    continue
                ok, _reason = log_service.validate_channel(guild, int(channel.id))
                if ok:
                    return channel
    return None


def _runtime_state(bot: commands.Bot) -> dict[str, Any]:
    state = getattr(bot, "live_log_delivery_v5_state", None)
    if not isinstance(state, dict):
        state = {
            "installed": False,
            "attempts": 0,
            "recovered_routes": 0,
            "successful_after_recovery": 0,
            "last_guild_id": None,
            "last_log_type": None,
            "last_channel_id": None,
            "last_result": None,
            "last_error": None,
            "last_at": None,
        }
        bot.live_log_delivery_v5_state = state
    return state


async def _repair_route(
    bot: commands.Bot,
    guild: discord.Guild,
    log_type: str,
    channel: discord.TextChannel,
) -> None:
    # Une DB Railway recréée peut ne même plus avoir la ligne guild_config.
    ensure = getattr(bot.db, "ensure_guild", None)
    if callable(ensure):
        await ensure(guild.id)

    # Point d'écriture unique. Les anciennes colonnes guild_config ne sont plus écrites :
    # log_config est la seule source de vérité du routage depuis la migration.
    await log_service.set_log_config(
        bot, guild.id, log_type, channel_id=channel.id, enabled=True
    )


async def send_log_v5(
    bot,
    guild: discord.Guild,
    log_type: str,
    embed: discord.Embed,
    file: discord.File | None = None,
    *,
    view: discord.ui.View | None = None,
    event_key: str | None = None,

    **identity,
) -> bool:
    state = _runtime_state(bot)
    state["attempts"] = int(state.get("attempts") or 0) + 1
    state.update({
        "last_guild_id": int(guild.id),
        "last_log_type": str(log_type),
        "last_channel_id": None,
        "last_result": None,
        "last_error": None,
        "last_at": int(time.time()),
    })

    setting = None
    try:
        setting = await log_service.get_log_setting(bot, guild.id, log_type)
    except Exception as exc:
        state["last_error"] = type(exc).__name__
        logger.exception("V5 : lecture route log impossible guild=%s type=%s.", guild.id, log_type)

    # Une route active et valide garde la priorité : aucune surprise pour une config saine.
    if setting and bool(setting.get("enabled")):
        ok, _reason = log_service.validate_channel(
            guild,
            setting.get("channel_id"),
            needs_file=file is not None,
        )
        if ok:
            state["last_channel_id"] = int(setting["channel_id"])
            result = await _canonical_send_log()(
                bot, guild, log_type, embed, file,
                view=view, event_key=event_key, **identity,
            )
            state["last_result"] = "normal_send_success" if result else "normal_send_rejected"
            return bool(result)

    # Si une route valide est volontairement désactivée, on respecte le choix admin.
    if setting and not bool(setting.get("enabled")) and setting.get("channel_id"):
        valid, _reason = log_service.validate_channel(guild, setting.get("channel_id"))
        if valid:
            state["last_channel_id"] = int(setting["channel_id"])
            state["last_result"] = "explicitly_disabled"
            return False

    # Route absente/cassée : découverte depuis la structure Discord visible en direct.
    candidate = _discover_channel(guild, log_type)
    if candidate is None:
        state["last_result"] = "no_live_channel_found"
        logger.warning(
            "V5 : aucun salon live reconnu guild=%s type=%s aliases=%s",
            guild.id,
            log_type,
            ",".join(_aliases(log_type)),
        )
        return False

    try:
        await _repair_route(bot, guild, log_type, candidate)
        state["recovered_routes"] = int(state.get("recovered_routes") or 0) + 1
        state["last_channel_id"] = int(candidate.id)
        logger.warning(
            "V5 : route log récupérée en direct guild=%s type=%s channel=%s (%s).",
            guild.id,
            log_type,
            candidate.id,
            candidate.name,
        )
    except Exception as exc:
        state["last_result"] = "repair_failed"
        state["last_error"] = type(exc).__name__
        logger.exception(
            "V5 : réparation route impossible guild=%s type=%s channel=%s.",
            guild.id,
            log_type,
            candidate.id,
        )
        return False

    result = await _canonical_send_log()(
        bot, guild, log_type, embed, file,
        view=view, event_key=event_key, **identity,
    )
    if result:
        state["successful_after_recovery"] = int(state.get("successful_after_recovery") or 0) + 1
        state["last_result"] = "recovered_and_sent"
    else:
        state["last_result"] = "recovered_but_send_failed"
    return bool(result)


def _install_health(bot: commands.Bot) -> None:
    try:
        from web import production_health
    except Exception:
        return
    current = production_health._safe_slash_health
    if getattr(current, "_sentrix_live_log_v5_health", False):
        return

    def health(runtime_bot: commands.Bot):
        payload = current(runtime_bot)
        if not isinstance(payload, dict):
            payload = {}
        payload["live_log_delivery_v5"] = dict(_runtime_state(runtime_bot))
        return payload

    health._sentrix_live_log_v5_health = True
    health._sentrix_original = current
    production_health._safe_slash_health = health


def install(bot: commands.Bot) -> None:
    global _CANONICAL_SEND_LOG
    current = log_service.send_log
    if getattr(current, _MARKER, False):
        _runtime_state(bot)["installed"] = True
        return

    # Capture le sender réellement en place au moment de l'installation.
    _CANONICAL_SEND_LOG = current
    send_log_v5._sentrix_original = current
    send_log_v5._sentrix_previous = current
    setattr(send_log_v5, _MARKER, True)
    log_service.send_log = send_log_v5
    state = _runtime_state(bot)
    state["installed"] = True
    _install_health(bot)
    logger.info("V5 logs actif : auto-réparation de route au moment de chaque événement.")


__all__ = ["install", "send_log_v5", "_discover_channel", "CHANNEL_ALIASES"]
