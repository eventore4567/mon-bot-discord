"""Santé des commandes : compte chaque erreur technique par commande et prévient
le propriétaire dès la PREMIÈRE occurrence d'une commande cassée.

Pourquoi ce module : ``cogs/production_ops.py`` n'alerte qu'à partir de 5 erreurs
techniques en 5 minutes. Une commande qui plante une fois par jour (``+clear 100``
→ SXR-CMD-0001, ClientException) n'y déclenche donc jamais rien, et seul le membre
qui a tapé la commande voit la référence. Ici :

- abonnement à ``core.errors.pipeline`` (la source unique des références SXR) —
  aucune interception de commande, aucun monkeypatch ;
- un compteur par commande (``bot._sentrix_command_health``), exposé par
  :func:`snapshot` pour ``/health`` et le sweep ``tools/command_sweep.py`` ;
- une alerte privée au destinataire ops (même cible que production_ops, donc le
  DM du créateur par défaut) dédoublonnée par (commande, transport, exception),
  une fois par ``SENTRIX_COMMAND_ALERT_COOLDOWN_SECONDS`` (6 h par défaut) ;
- jamais de contenu de message, de token ni de paramètre SQL dans l'alerte :
  seulement la commande, le type d'exception, la référence et le nombre d'occurrences.

Aucune commande Discord n'est ajoutée.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import discord
from discord.ext import commands

from core.errors import pipeline as error_pipeline

logger = logging.getLogger("bot.command-health")

DEFAULT_COOLDOWN_SECONDS = 6 * 60 * 60
# Erreurs « utilisateur » : elles passent par le pipeline uniquement si un
# gestionnaire les y envoie par erreur ; elles ne signalent pas une commande cassée.
_USER_ERRORS = frozenset({
    "CommandNotFound", "BadArgument", "MissingRequiredArgument", "TooManyArguments",
    "MemberNotFound", "UserNotFound", "RoleNotFound", "ChannelNotFound",
    "CommandOnCooldown", "MissingPermissions", "BotMissingPermissions",
    "NoPrivateMessage", "CheckFailure", "Forbidden", "NotFound",
})


def _positive_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _state(bot: commands.Bot) -> dict[str, Any]:
    current = getattr(bot, "_sentrix_command_health", None)
    if isinstance(current, dict):
        return current
    current = {
        "installed": False,
        "since": int(time.time()),
        "commands": {},      # "clear" -> {"errors", "last_at", "last_code", "last_exc", "transports"}
        "alerts": {},        # "clear|prefix|ClientException" -> dernier envoi (epoch)
        "alerts_sent": 0,
        "last_alert_error": None,
    }
    bot._sentrix_command_health = current
    return current


def _record(bot: commands.Bot, entry: error_pipeline.ErrorReport) -> dict[str, Any]:
    state = _state(bot)
    commands_state = state["commands"]
    row = commands_state.get(entry.command)
    if row is None:
        row = {"errors": 0, "last_at": None, "last_code": None, "last_exc": None, "transports": []}
        commands_state[entry.command] = row
    row["errors"] += 1
    row["last_at"] = int(entry.created_at)
    row["last_code"] = entry.code
    row["last_exc"] = entry.exc_type
    if entry.transport not in row["transports"]:
        row["transports"].append(entry.transport)
    return row


def _is_primary_service() -> bool:
    try:
        from .production_alert_noise_fix import _is_primary_service as primary
    except Exception:
        return True
    try:
        return bool(primary())
    except Exception:
        return True


def _release(bot: commands.Bot) -> str:
    obs = getattr(bot, "_sentrix_observability_v26", None)
    if isinstance(obs, dict):
        return str(obs.get("release") or "inconnu")[:20]
    return "inconnu"


def format_alert(entry: error_pipeline.ErrorReport, occurrences: int, release: str) -> str:
    prefix = "/" if entry.transport == "slash" else "+"
    return (
        "🛠️ **SentriX — commande en erreur**\n"
        f"Commande : `{prefix}{entry.command}` ({'slash' if entry.transport == 'slash' else 'préfixe'})\n"
        f"Erreur : `{entry.exc_type}`\n"
        f"Référence : `{entry.code}` (la trace complète est dans les logs, `grep {entry.code}`)\n"
        f"Occurrences depuis le démarrage : {occurrences}\n"
        f"Release : `{release}`\n"
        "Aucun contenu de message, token ou paramètre SQL n'est inclus dans cette alerte."
    )


async def _notify(bot: commands.Bot, entry: error_pipeline.ErrorReport, occurrences: int) -> None:
    state = _state(bot)
    key = f"{entry.command}|{entry.transport}|{entry.exc_type}"
    now_value = int(time.time())
    cooldown = _positive_int_env(
        "SENTRIX_COMMAND_ALERT_COOLDOWN_SECONDS", DEFAULT_COOLDOWN_SECONDS, minimum=300, maximum=7 * 86400
    )
    last = int(state["alerts"].get(key) or 0)
    if now_value - last < cooldown:
        return
    if not _is_primary_service():
        logger.debug("Alerte commande ignorée sur le service secondaire : %s", key)
        return

    try:
        from . import production_ops
        target = await production_ops._resolve_alert_target(bot)
    except Exception:
        target = None
    if target is None:
        state["last_alert_error"] = "target_unavailable"
        logger.error("Alerte commande non envoyée (cible indisponible) : %s %s", key, entry.code)
        return
    try:
        await target.send(
            format_alert(entry, occurrences, _release(bot)),
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except (discord.Forbidden, discord.HTTPException) as exc:
        state["last_alert_error"] = type(exc).__name__
        logger.exception("Impossible d'envoyer l'alerte commande SentriX.")
        return
    state["alerts"][key] = now_value
    state["alerts_sent"] = int(state.get("alerts_sent") or 0) + 1
    state["last_alert_error"] = None


def _make_listener(bot: commands.Bot):
    def on_report(entry: error_pipeline.ErrorReport) -> None:
        row = _record(bot, entry)
        if entry.exc_type in _USER_ERRORS:
            return
        # Le pipeline est synchrone : on planifie l'envoi sans bloquer la commande.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(_notify(bot, entry, int(row["errors"])))

    on_report.__qualname__ = "command_health.on_report"
    return on_report


def snapshot(bot: commands.Bot, *, limit: int = 10) -> dict[str, Any]:
    """Classement des commandes les plus fragiles depuis le démarrage (sans données personnelles)."""
    state = _state(bot)
    rows = [
        {"command": name, **dict(row)}
        for name, row in state["commands"].items()
    ]
    rows.sort(key=lambda row: (-int(row["errors"]), -int(row["last_at"] or 0), row["command"]))
    return {
        "since": state["since"],
        "total_errors": sum(int(row["errors"]) for row in rows),
        "broken_commands": len(rows),
        "alerts_sent": int(state.get("alerts_sent") or 0),
        "last_alert_error": state.get("last_alert_error"),
        "top": rows[:limit],
    }


def install(bot: commands.Bot) -> None:
    state = _state(bot)
    if state.get("installed"):
        return
    listener = _make_listener(bot)
    error_pipeline.subscribe(listener)
    state["installed"] = True
    state["listener"] = listener
    logger.info("Santé des commandes active : alerte privée dès la première erreur technique, 0 nouvelle commande.")


async def setup(bot: commands.Bot) -> None:
    install(bot)
