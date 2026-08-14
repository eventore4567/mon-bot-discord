"""Detecte les anciennes integrations Discord qui peuvent dupliquer SentriX.

Le bug persistant des commandes slash montre qu'une interaction visible dans Discord ne
rejoint ni l'instance SentriX ni l'instance Odboug actuellement deployees. Cette couche
inspecte donc les integrations des serveurs ou le bot possede Gérer le serveur et signale
uniquement les applications dont le nom ressemble a la marque courante mais dont l'ID
application est different.

Aucune integration n'est supprimee ici. Les guild IDs et integration IDs restent internes
au processus et ne sont jamais exposes par /health.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time

import discord
from discord.ext import commands
from discord.http import Route

from utils import instance_identity

logger = logging.getLogger("bot.stale-discord-app-detector")
_MAX_GUILDS = 250


def _normalized(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _brand_aliases() -> set[str]:
    brand = instance_identity.brand_label()
    aliases = {_normalized(brand)}
    if brand.casefold() == "sentrix":
        aliases.update({"sentrixbot", "botsentrix"})
    elif brand.casefold() == "odboug":
        aliases.update({"odbougbot", "botodboug"})
    return {item for item in aliases if item}


def _looks_like_current_brand(application_name: object, bot_name: object) -> bool:
    aliases = _brand_aliases()
    app = _normalized(application_name)
    user = _normalized(bot_name)
    return bool(app in aliases or user in aliases)


def _state(bot: commands.Bot) -> dict:
    state = getattr(bot, "stale_discord_app_detector_state", None)
    if not isinstance(state, dict):
        state = {
            "installed": False,
            "scan_started_at": None,
            "scan_completed_at": None,
            "scanned_guilds": 0,
            "eligible_guilds": 0,
            "scan_errors": 0,
            "candidate_count": 0,
            "candidate_apps": [],
            "last_error": None,
            # Interne uniquement : utilise plus tard pour un nettoyage cible si necessaire.
            "candidate_targets": [],
        }
        bot.stale_discord_app_detector_state = state
    return state


def _safe_health(bot: commands.Bot) -> dict:
    state = _state(bot)
    safe_candidates = []
    for candidate in list(state.get("candidate_apps") or [])[:20]:
        if not isinstance(candidate, dict):
            continue
        safe_candidates.append({
            "application_id": candidate.get("application_id"),
            "application_name": candidate.get("application_name"),
            "bot_user_id": candidate.get("bot_user_id"),
            "bot_user_name": candidate.get("bot_user_name"),
            "guild_count": int(candidate.get("guild_count") or 0),
        })
    return {
        "installed": bool(state.get("installed")),
        "scan_started_at": state.get("scan_started_at"),
        "scan_completed_at": state.get("scan_completed_at"),
        "scanned_guilds": int(state.get("scanned_guilds") or 0),
        "eligible_guilds": int(state.get("eligible_guilds") or 0),
        "scan_errors": int(state.get("scan_errors") or 0),
        "candidate_count": int(state.get("candidate_count") or 0),
        "candidate_apps": safe_candidates,
        "last_error": state.get("last_error"),
    }


def _install_health_patch() -> None:
    try:
        from web import production_health
    except Exception:
        return

    current = production_health._safe_slash_health
    if getattr(current, "_sentrix_stale_app_detector", False):
        return

    def safe_slash_health_with_stale_apps(bot):
        payload = current(bot)
        if not isinstance(payload, dict):
            payload = {}
        payload["stale_app_detector"] = _safe_health(bot)
        return payload

    safe_slash_health_with_stale_apps._sentrix_stale_app_detector = True
    safe_slash_health_with_stale_apps._sentrix_original = current
    production_health._safe_slash_health = safe_slash_health_with_stale_apps


async def _fetch_guild_integrations(bot: commands.Bot, guild_id: int) -> list[dict]:
    data = await bot.http.request(Route("GET", "/guilds/{guild_id}/integrations", guild_id=guild_id))
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _candidate_fields(integration: dict) -> tuple[str | None, str | None, str | None, str | None]:
    application = integration.get("application") if isinstance(integration.get("application"), dict) else {}
    user = integration.get("user") if isinstance(integration.get("user"), dict) else {}
    bot = application.get("bot") if isinstance(application.get("bot"), dict) else {}
    bot_user = bot or user
    application_id = str(application.get("id") or "") or None
    application_name = str(application.get("name") or "")[:100] or None
    bot_user_id = str(bot_user.get("id") or "") or None
    bot_user_name = str(bot_user.get("username") or bot_user.get("global_name") or "")[:100] or None
    return application_id, application_name, bot_user_id, bot_user_name


async def _scan(bot: commands.Bot) -> None:
    await bot.wait_until_ready()
    # Laisse les autres gardes de demarrage (transport/sync) finir avant l'inventaire.
    await asyncio.sleep(8)
    state = _state(bot)
    state.update({
        "scan_started_at": int(time.time()),
        "scan_completed_at": None,
        "scanned_guilds": 0,
        "eligible_guilds": 0,
        "scan_errors": 0,
        "candidate_count": 0,
        "candidate_apps": [],
        "candidate_targets": [],
        "last_error": None,
    })

    current_application_id = str(getattr(bot.user, "id", ""))
    aggregated: dict[str, dict] = {}
    targets: list[dict] = []

    try:
        for guild in list(bot.guilds)[:_MAX_GUILDS]:
            state["scanned_guilds"] += 1
            me = guild.me
            if me is None or not me.guild_permissions.manage_guild:
                continue
            state["eligible_guilds"] += 1
            try:
                integrations = await _fetch_guild_integrations(bot, guild.id)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                state["scan_errors"] += 1
                continue

            for integration in integrations:
                application_id, application_name, bot_user_id, bot_user_name = _candidate_fields(integration)
                if not application_id or application_id == current_application_id:
                    continue
                if not _looks_like_current_brand(application_name, bot_user_name):
                    continue

                key = application_id
                item = aggregated.setdefault(key, {
                    "application_id": application_id,
                    "application_name": application_name,
                    "bot_user_id": bot_user_id,
                    "bot_user_name": bot_user_name,
                    "guild_count": 0,
                    "_guilds": set(),
                })
                if guild.id not in item["_guilds"]:
                    item["_guilds"].add(guild.id)
                    item["guild_count"] += 1
                targets.append({
                    "guild_id": int(guild.id),
                    "integration_id": str(integration.get("id") or ""),
                    "application_id": application_id,
                })

        candidates = []
        for item in aggregated.values():
            item.pop("_guilds", None)
            candidates.append(item)
        candidates.sort(key=lambda item: (-int(item.get("guild_count") or 0), item.get("application_id") or ""))
        state["candidate_apps"] = candidates[:20]
        state["candidate_targets"] = targets[:500]
        state["candidate_count"] = len(candidates)
        state["scan_completed_at"] = int(time.time())
        if candidates:
            logger.warning(
                "Ancienne(s) application(s) Discord ressemblant a %s detectee(s): %s candidat(s).",
                instance_identity.brand_label(),
                len(candidates),
            )
        else:
            logger.info("Aucune integration Discord dupliquee pour %s detectee.", instance_identity.brand_label())
    except Exception as exc:
        state["last_error"] = type(exc).__name__
        state["scan_completed_at"] = int(time.time())
        logger.exception("Echec de l'inventaire des integrations Discord dupliquees.")


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_stale_discord_app_detector_installed", False):
        return
    bot._sentrix_stale_discord_app_detector_installed = True
    state = _state(bot)
    state["installed"] = True
    _install_health_patch()
    bot._sentrix_stale_discord_app_detector_task = asyncio.create_task(_scan(bot))


async def setup(bot: commands.Bot) -> None:
    install(bot)
