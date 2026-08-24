"""Synchronisation SentriX avec les annuaires de bots.

Variables optionnelles :
- TOPGG_TOKEN : token API Top.gg
- DISCORDBOTLIST_TOKEN : token API généré sur la fiche DiscordBotList

DiscordBotList :
- stats : POST /api/v1/bots/:id/stats avec le token brut
- commands : POST /api/v1/bots/:id/commands avec Authorization: Bot <token>

Les erreurs d'un annuaire ne doivent jamais empêcher SentriX, Discord ou le dashboard
de fonctionner. Les secrets restent uniquement dans les variables d'environnement.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from aiohttp import ClientSession, ClientTimeout, web

logger = logging.getLogger("bot.dashboard.bot-directory-stats-v44")
_INSTALLED = False
_STATS_INTERVAL_SECONDS = 30 * 60
_COMMAND_SUCCESS_INTERVAL_SECONDS = 6 * 60 * 60
_COMMAND_RETRY_MIN_SECONDS = 60
_COMMAND_RETRY_MAX_SECONDS = 10 * 60
_WORKER_TICK_SECONDS = 20


def _clean_env(name: str) -> str:
    return str(os.getenv(name, "") or "").strip()


def _snapshot(bot) -> dict[str, int]:
    guilds = list(getattr(bot, "guilds", []) or [])
    return {
        "guilds": len(guilds),
        "users": sum(int(getattr(guild, "member_count", 0) or 0) for guild in guilds),
        "shards": max(1, int(getattr(bot, "shard_count", 0) or 1)),
    }


def _command_auth(token: str) -> str:
    """La doc Commands exige exactement `Authorization: Bot <token>`."""
    token = str(token or "").strip()
    if token.casefold().startswith("bot "):
        return token
    return f"Bot {token}"


def _raw_auth(token: str) -> str:
    """Stats/Vote API utilisent le token d'annuaire brut."""
    token = str(token or "").strip()
    if token.casefold().startswith("bot "):
        return token[4:].strip()
    return token


def _command_type_value(command) -> int:
    value = getattr(command, "type", 1)
    raw = getattr(value, "value", value)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 1


def _serialize_commands(commands) -> list[dict[str, Any]]:
    """Payload minimal conforme à l'exemple officiel DiscordBotList.

    DiscordBotList affiche les slash commands de type CHAT_INPUT. Pour maximiser la
    compatibilité avec leur validateur, on envoie uniquement name/description/type.
    """
    payload: list[dict[str, Any]] = []
    seen: set[str] = set()

    for command in commands:
        if _command_type_value(command) != 1:
            continue

        name = str(getattr(command, "name", "") or "").strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)

        description = str(getattr(command, "description", "") or "Commande SentriX").strip()
        if not description:
            description = "Commande SentriX"

        # Limites Discord pour une commande CHAT_INPUT.
        payload.append({
            "name": name[:32],
            "description": description[:100],
            "type": 1,
        })

    return payload


async def _command_payload(bot) -> tuple[list[dict[str, Any]], str]:
    """Récupère d'abord les commandes réellement enregistrées chez Discord."""
    tree = getattr(bot, "tree", None)
    if tree is None:
        return [], "no_tree"

    try:
        registered = list(await tree.fetch_commands())
        payload = _serialize_commands(registered)
        if payload:
            return payload, "discord_registered"
        logger.warning("DiscordBotList : Discord ne renvoie aucune slash command globale exploitable.")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("DiscordBotList : impossible de récupérer les commandes globales chez Discord.")

    # Fallback : l'arbre local est déjà chargé et tree.sync() est exécuté avant le
    # démarrage du dashboard dans main.py.
    try:
        local = list(tree.get_commands())
        return _serialize_commands(local), "local_tree"
    except Exception:
        logger.exception("DiscordBotList : impossible de lire l'arbre local des commandes.")
        return [], "local_error"


def _safe_http_reason(status: int | None) -> str:
    if status is None:
        return "request_error"
    if 200 <= status < 300:
        return "ok"
    if status == 400:
        return "invalid_payload"
    if status == 401:
        return "invalid_or_expired_token"
    if status == 403:
        return "forbidden"
    if status == 404:
        return "bot_or_endpoint_not_found"
    if status == 429:
        return "rate_limited"
    if 500 <= status < 600:
        return "discordbotlist_server_error"
    return f"http_{status}"


async def _post_json(
    session: ClientSession,
    *,
    url: str,
    headers: dict[str, str],
    payload: Any,
    label: str,
) -> dict[str, Any]:
    status: int | None = None
    try:
        async with session.post(url, headers=headers, json=payload) as response:
            status = int(response.status)
            # Lire le body pour libérer correctement la connexion, mais ne jamais le
            # stocker dans l'état public : certains services peuvent y inclure des détails.
            body = (await response.text())[:500]
            ok = 200 <= status < 300
            if ok:
                logger.info("%s : HTTP %s.", label, status)
            else:
                logger.warning("%s refusé : HTTP %s — %s", label, status, body)
            return {"ok": ok, "http_status": status, "reason": _safe_http_reason(status)}
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("%s : requête impossible.", label)
        return {
            "ok": False,
            "http_status": status,
            "reason": f"request_error:{type(exc).__name__}",
        }


def _base_state(bot) -> dict[str, Any]:
    return {
        "updated_at": None,
        "stats": _snapshot(bot),
        "results": {},
        "commands": {},
        "configured": {
            "topgg": bool(_clean_env("TOPGG_TOKEN")),
            "discordbotlist": bool(_clean_env("DISCORDBOTLIST_TOKEN")),
        },
    }


def _state(bot) -> dict[str, Any]:
    state = getattr(bot, "_sentrix_directory_stats", None)
    if not isinstance(state, dict):
        state = _base_state(bot)
    return state


async def _post_stats_once(bot) -> dict[str, Any]:
    if not getattr(bot, "user", None) or not bot.is_ready():
        return {}

    topgg_token = _clean_env("TOPGG_TOKEN")
    dbl_token = _clean_env("DISCORDBOTLIST_TOKEN")
    if not topgg_token and not dbl_token:
        return {}

    stats = _snapshot(bot)
    results: dict[str, Any] = {}
    timeout = ClientTimeout(total=15, connect=6)

    async with ClientSession(timeout=timeout) as session:
        if topgg_token:
            results["topgg"] = await _post_json(
                session,
                url="https://top.gg/api/v1/projects/@me/metrics",
                headers={
                    "Authorization": f"Bearer {topgg_token}",
                    "Content-Type": "application/json",
                    "User-Agent": "SentriX/1.0 directory-stats",
                },
                payload={
                    "server_count": stats["guilds"],
                    "shard_count": stats["shards"],
                },
                label="Top.gg stats",
            )

        if dbl_token:
            results["discordbotlist"] = await _post_json(
                session,
                url=f"https://discordbotlist.com/api/v1/bots/{bot.user.id}/stats",
                headers={
                    "Authorization": _raw_auth(dbl_token),
                    "Content-Type": "application/json",
                    "User-Agent": "SentriX/1.0 directory-stats",
                },
                payload={
                    "guilds": stats["guilds"],
                    "users": stats["users"],
                    "voice_connections": len(getattr(bot, "voice_clients", []) or []),
                },
                label="DiscordBotList stats",
            )

    state = _state(bot)
    state.update({
        "updated_at": int(time.time()),
        "stats": stats,
        "results": results,
        "configured": {
            "topgg": bool(topgg_token),
            "discordbotlist": bool(dbl_token),
        },
    })
    bot._sentrix_directory_stats = state
    return results


async def _sync_discordbotlist_commands(bot) -> bool | None:
    token = _clean_env("DISCORDBOTLIST_TOKEN")
    if not token or not getattr(bot, "user", None) or not bot.is_ready():
        return None

    commands, source = await _command_payload(bot)
    now = int(time.time())
    state = _state(bot)

    if not commands:
        state["commands"] = {
            "updated_at": now,
            "count": 0,
            "ok": False,
            "source": source,
            "http_status": None,
            "reason": "no_commands_found",
        }
        bot._sentrix_directory_stats = state
        logger.warning("DiscordBotList commands : aucune slash command trouvée.")
        return False

    timeout = ClientTimeout(total=20, connect=6)
    async with ClientSession(timeout=timeout) as session:
        result = await _post_json(
            session,
            url=f"https://discordbotlist.com/api/v1/bots/{bot.user.id}/commands",
            headers={
                "Authorization": _command_auth(token),
                "Content-Type": "application/json",
                "User-Agent": "SentriX/1.0 directory-commands",
            },
            payload=commands,
            label=f"DiscordBotList commands ({len(commands)})",
        )

    state["commands"] = {
        "updated_at": now,
        "count": len(commands),
        "ok": bool(result["ok"]),
        "source": source,
        "http_status": result["http_status"],
        "reason": result["reason"],
    }
    bot._sentrix_directory_stats = state
    return bool(result["ok"])


async def _worker(bot) -> None:
    """Publie les stats et insiste sur Commands jusqu'à une vraie réussite HTTP 2xx."""
    try:
        await bot.wait_until_ready()
        # main.py exécute tree.sync() avant start_dashboard(); ce délai laisse seulement
        # les caches et connexions se stabiliser.
        await asyncio.sleep(15)

        next_stats = 0.0
        next_commands = 0.0
        command_retry = _COMMAND_RETRY_MIN_SECONDS

        while not bot.is_closed():
            now = time.monotonic()

            if now >= next_stats:
                await _post_stats_once(bot)
                next_stats = now + _STATS_INTERVAL_SECONDS

            if _clean_env("DISCORDBOTLIST_TOKEN") and now >= next_commands:
                ok = await _sync_discordbotlist_commands(bot)
                if ok:
                    next_commands = now + _COMMAND_SUCCESS_INTERVAL_SECONDS
                    command_retry = _COMMAND_RETRY_MIN_SECONDS
                else:
                    # En cas de 400/401/429/erreur réseau, ne pas attendre six heures.
                    next_commands = now + command_retry
                    command_retry = min(command_retry * 2, _COMMAND_RETRY_MAX_SECONDS)

            await asyncio.sleep(_WORKER_TICK_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Le worker d'annuaires SentriX s'est arrêté de façon inattendue.")


async def directory_status(request: web.Request) -> web.Response:
    """Diagnostic sans secrets et sans réponse brute d'un service tiers."""
    bot = request.app["bot"]
    state = _state(bot)
    # Rafraîchir les booléens : une variable peut avoir changé après un redeploy.
    state["configured"] = {
        "topgg": bool(_clean_env("TOPGG_TOKEN")),
        "discordbotlist": bool(_clean_env("DISCORDBOTLIST_TOKEN")),
    }
    return web.json_response(
        state,
        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"},
    )


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        app.router.add_get("/api/directory-status", directory_status)

        async def start_directory_worker(_app):
            if not (_clean_env("TOPGG_TOKEN") or _clean_env("DISCORDBOTLIST_TOKEN")):
                logger.info("Stats annuaires : aucun token configuré, module en veille.")
                _app["sentrix_directory_stats_task"] = None
                return
            _app["sentrix_directory_stats_task"] = asyncio.create_task(
                _worker(bot),
                name="sentrix-directory-stats",
            )

        async def stop_directory_worker(_app):
            task = _app.get("sentrix_directory_stats_task")
            if task is None:
                return
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        app.on_startup.append(start_directory_worker)
        app.on_cleanup.append(stop_directory_worker)
        return app

    dashboard.build_app = build_app
