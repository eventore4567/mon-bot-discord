"""Force le transport des interactions Discord vers le Gateway utilise par SentriX.

Discord permet de recevoir les interactions soit via INTERACTION_CREATE (Gateway), soit via
un Interactions Endpoint URL HTTP. Ces deux modes sont mutuellement exclusifs. SentriX est
un bot discord.py connecte au Gateway et ne sert aucun endpoint Discord signe ; un ancien
Interactions Endpoint URL ferait donc partir les commandes slash vers un ancien service.

Cette garde verifie l'application associee au token apres READY. Si un endpoint HTTP est
encore configure, elle le retire via l'API officielle puis resynchronise le catalogue slash.
Aucun token ni URL d'endpoint n'est expose dans les logs ou /health.
"""
from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord.ext import commands
from discord.http import Route

logger = logging.getLogger("bot.interaction-transport")


def _state(bot: commands.Bot) -> dict:
    state = getattr(bot, "interaction_transport_guard_state", None)
    if not isinstance(state, dict):
        state = {
            "installed": False,
            "checked_at": None,
            "application_id": None,
            "endpoint_was_configured": None,
            "clear_attempted": False,
            "gateway_confirmed": False,
            "cleared_at": None,
            "resynced_commands": None,
            "last_error": None,
        }
        bot.interaction_transport_guard_state = state
    return state


def _safe_health(bot: commands.Bot) -> dict:
    state = _state(bot)
    return {
        "installed": bool(state.get("installed")),
        "checked_at": state.get("checked_at"),
        "application_id": state.get("application_id"),
        "endpoint_was_configured": state.get("endpoint_was_configured"),
        "clear_attempted": bool(state.get("clear_attempted")),
        "gateway_confirmed": bool(state.get("gateway_confirmed")),
        "cleared_at": state.get("cleared_at"),
        "resynced_commands": state.get("resynced_commands"),
        "last_error": state.get("last_error"),
    }


def _install_health_patch() -> None:
    """Ajoute l'etat du transport au bloc slash existant de /health."""
    try:
        from web import production_health
    except Exception:
        return

    current = production_health._safe_slash_health
    if getattr(current, "_sentrix_transport_guard", False):
        return

    def safe_slash_health_with_transport(bot):
        payload = current(bot)
        if not isinstance(payload, dict):
            payload = {}
        payload["interaction_transport"] = _safe_health(bot)
        return payload

    safe_slash_health_with_transport._sentrix_transport_guard = True
    safe_slash_health_with_transport._sentrix_original = current
    production_health._safe_slash_health = safe_slash_health_with_transport


async def _get_current_application(bot: commands.Bot) -> dict:
    data = await bot.http.request(Route("GET", "/applications/@me"))
    return data if isinstance(data, dict) else {}


async def _clear_interactions_endpoint(bot: commands.Bot) -> dict:
    data = await bot.http.request(
        Route("PATCH", "/applications/@me"),
        json={"interactions_endpoint_url": None},
    )
    return data if isinstance(data, dict) else {}


async def _enforce_gateway_transport(bot: commands.Bot) -> None:
    await bot.wait_until_ready()
    state = _state(bot)
    state["checked_at"] = int(time.time())
    state["last_error"] = None

    try:
        application = await _get_current_application(bot)
        application_id = str(application.get("id") or getattr(bot.user, "id", "")) or None
        endpoint_configured = bool(application.get("interactions_endpoint_url"))
        state["application_id"] = application_id
        state["endpoint_was_configured"] = endpoint_configured

        if endpoint_configured:
            state["clear_attempted"] = True
            logger.warning(
                "Un ancien Interactions Endpoint HTTP est configure pour l'application %s ; "
                "bascule automatique vers le Gateway SentriX.",
                application_id,
            )
            await _clear_interactions_endpoint(bot)
            verification = await _get_current_application(bot)
            if verification.get("interactions_endpoint_url"):
                raise RuntimeError("INTERACTIONS_ENDPOINT_STILL_CONFIGURED")
            state["cleared_at"] = int(time.time())
        else:
            state["clear_attempted"] = False

        # Une fois le transport Gateway confirme, republie aussi le catalogue actuel afin
        # que les commandes visibles correspondent exactement au runtime qui les recevra.
        synced = await bot.tree.sync()
        state["resynced_commands"] = len(synced)
        state["gateway_confirmed"] = True
        logger.info(
            "Transport interactions Discord confirme sur Gateway (application=%s, endpoint_http_avant=%s, slash=%s).",
            application_id,
            endpoint_configured,
            len(synced),
        )
    except discord.HTTPException as exc:
        state["gateway_confirmed"] = False
        state["last_error"] = f"DiscordHTTP:{getattr(exc, 'status', 'unknown')}"
        logger.exception("Impossible de verifier/corriger le transport des interactions Discord.")
    except Exception as exc:
        state["gateway_confirmed"] = False
        state["last_error"] = type(exc).__name__
        logger.exception("Impossible de verifier/corriger le transport des interactions Discord.")


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_interaction_transport_guard_installed", False):
        return
    bot._sentrix_interaction_transport_guard_installed = True
    state = _state(bot)
    state["installed"] = True
    _install_health_patch()
    bot._sentrix_interaction_transport_guard_task = asyncio.create_task(_enforce_gateway_transport(bot))


async def setup(bot: commands.Bot) -> None:
    install(bot)
