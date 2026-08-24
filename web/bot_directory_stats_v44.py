"""Publication optionnelle des statistiques et commandes SentriX vers les annuaires.

Le module est sans effet tant qu'aucun token n'est configuré dans l'environnement.
Aucun secret n'est stocké en base ou exposé au dashboard.

Variables prises en charge :
- TOPGG_TOKEN : token API v1 Top.gg (Bearer)
- DISCORDBOTLIST_TOKEN : token API DiscordBotList

Les statistiques sont publiées au démarrage lorsque Discord est prêt, puis toutes les
30 minutes. La liste des slash commands DiscordBotList est synchronisée au démarrage
puis toutes les 6 heures. Une erreur d'annuaire n'affecte jamais Discord, le dashboard
ni Railway.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

from aiohttp import ClientSession, ClientTimeout, web

logger = logging.getLogger("bot.dashboard.bot-directory-stats-v44")
_INSTALLED = False
_INTERVAL_SECONDS = 30 * 60
_COMMAND_SYNC_INTERVAL_SECONDS = 6 * 60 * 60


def _clean_env(name: str) -> str:
    return str(os.getenv(name, "") or "").strip()


def _snapshot(bot) -> dict[str, int]:
    guilds = list(getattr(bot, "guilds", []) or [])
    return {
        "guilds": len(guilds),
        "users": sum(int(getattr(guild, "member_count", 0) or 0) for guild in guilds),
        "shards": max(1, int(getattr(bot, "shard_count", 0) or 1)),
    }


def _discordbotlist_command_auth(token: str) -> str:
    """L'endpoint Commands exige `Authorization: Bot <token>`."""
    token = str(token or "").strip()
    if token.casefold().startswith("bot "):
        return token
    return f"Bot {token}"


def _discordbotlist_raw_auth(token: str) -> str:
    """Les endpoints Stats/Vote API utilisent le token brut dans Authorization."""
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


def _serialize_commands(commands) -> list[dict]:
    """Construit le payload minimal montré par la documentation DiscordBotList.

    DiscordBotList n'a besoin que de name/description/type pour afficher le bouton
    Commands. Envoyer le JSON Discord complet peut inclure des champs récents que leur
    validateur ne connaît pas encore. On limite donc volontairement le payload aux
    commandes slash CHAT_INPUT (type 1).
    """
    payload: list[dict] = []
    seen: set[str] = set()

    for command in commands:
        command_type = _command_type_value(command)
        if command_type != 1:
            continue

        name = str(getattr(command, "name", "") or "").strip()
        if not name:
            continue
        marker = name.casefold()
        if marker in seen:
            continue
        seen.add(marker)

        description = str(getattr(command, "description", "") or "Commande SentriX").strip()
        if not description:
            description = "Commande SentriX"

        payload.append(
            {
                "name": name[:32],
                "description": description[:100],
                "type": 1,
            }
        )

    return payload


async def _command_payload(bot) -> tuple[list[dict], str]:
    """Préfère les slash commands réellement enregistrées chez Discord."""
    tree = getattr(bot, "tree", None)
    if tree is None:
        return [], "no_tree"

    try:
        registered = list(await tree.fetch_commands())
        payload = _serialize_commands(registered)
        if payload:
            return payload, "discord_registered_minimal"
        logger.warning("DiscordBotList commands : Discord ne renvoie aucune slash command globale exploitable.")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Impossible de récupérer les slash commands enregistrées chez Discord.")

    try:
        local = list(tree.get_commands())
    except Exception:
        logger.exception("Impossible de lire l'arbre local des commandes slash SentriX.")
        return [], "local_error"

    return _serialize_commands(local), "local_tree_minimal"


async def _request(
    session: ClientSession,
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    payload,
    label: str,
) -> bool:
    try:
        async with session.request(method, url, headers=headers, json=payload) as response:
            if 200 <= response.status < 300:
                logger.info("Annuaire mis à jour : %s (%s).", label, response.status)
                return True
            body = (await response.text())[:500]
            logger.warning(
                "Mise à jour %s refusée : HTTP %s — %s",
                label,
                response.status,
                body,
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Impossible de publier vers %s.", label)
    return False


async def _post_stats_once(bot) -> dict[str, bool]:
    if not getattr(bot, "user", None) or not bot.is_ready():
        return {}

    topgg_token = _clean_env("TOPGG_TOKEN")
    dbl_token = _clean_env("DISCORDBOTLIST_TOKEN")
    if not topgg_token and not dbl_token:
        return {}

    stats = _snapshot(bot)
    results: dict[str, bool] = {}
    timeout = ClientTimeout(total=15, connect=6)

    async with ClientSession(timeout=timeout) as session:
        if topgg_token:
            results["topgg"] = await _request(
                session,
                method="PATCH",
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
            results["discordbotlist"] = await _request(
                session,
                method="POST",
                url=f"https://discordbotlist.com/api/v1/bots/{bot.user.id}/stats",
                headers={
                    "Authorization": _discordbotlist_raw_auth(dbl_token),
                    "Content-Type": "application/json",
                    "User-Agent": "SentriX/1.0 directory-stats",
                },
                payload={
                    "guilds": stats["guilds"],
                    "users": stats["users"],
                },
                label="DiscordBotList stats",
            )

    previous = getattr(bot, "_sentrix_directory_stats", None)
    command_state = previous.get("commands", {}) if isinstance(previous, dict) else {}
    bot._sentrix_directory_stats = {
        "updated_at": int(time.time()),
        "stats": stats,
        "results": results,
        "commands": command_state,
        "configured": {
            "topgg": bool(topgg_token),
            "discordbotlist": bool(dbl_token),
        },
    }
    return results


async def _sync_discordbotlist_commands(bot) -> bool | None:
    token = _clean_env("DISCORDBOTLIST_TOKEN")
    if not token or not getattr(bot, "user", None) or not bot.is_ready():
        return None

    commands, source = await _command_payload(bot)
    if not commands:
        logger.warning("DiscordBotList commands : aucune slash command trouvée, envoi ignoré.")
        state = getattr(bot, "_sentrix_directory_stats", None)
        if not isinstance(state, dict):
            state = {}
        state["commands"] = {
            "updated_at": int(time.time()),
            "count": 0,
            "ok": False,
            "source": source,
            "http_status": None,
            "response": "no_commands_found",
        }
        bot._sentrix_directory_stats = state
        return False

    timeout = ClientTimeout(total=20, connect=6)
    ok = False
    http_status = None
    response_body = ""
    try:
        async with ClientSession(timeout=timeout) as session:
            async with session.post(
                f"https://discordbotlist.com/api/v1/bots/{bot.user.id}/commands",
                headers={
                    "Authorization": _discordbotlist_command_auth(token),
                    "Content-Type": "application/json",
                    "User-Agent": "SentriX/1.0 directory-commands",
                },
                json=commands,
            ) as response:
                http_status = int(response.status)
                response_body = (await response.text())[:500]
                ok = 200 <= response.status < 300
                if ok:
                    logger.info(
                        "DiscordBotList commands synchronisées : HTTP %s, %s commande(s), source=%s.",
                        response.status,
                        len(commands),
                        source,
                    )
                else:
                    logger.warning(
                        "DiscordBotList commands refusées : HTTP %s — %s",
                        response.status,
                        response_body,
                    )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        response_body = f"request_error:{type(exc).__name__}"
        logger.exception("Impossible de publier les commandes vers DiscordBotList.")

    state = getattr(bot, "_sentrix_directory_stats", None)
    if not isinstance(state, dict):
        state = {
            "updated_at": None,
            "stats": _snapshot(bot),
            "results": {},
            "configured": {
                "topgg": bool(_clean_env("TOPGG_TOKEN")),
                "discordbotlist": True,
            },
        }
    state["commands"] = {
        "updated_at": int(time.time()),
        "count": len(commands),
        "ok": bool(ok),
        "source": source,
        "http_status": http_status,
        "response": response_body or ("ok" if ok else "empty_response"),
    }
    bot._sentrix_directory_stats = state
    return ok


async def _worker(bot) -> None:
    try:
        await bot.wait_until_ready()
        await asyncio.sleep(10)
        next_command_sync = 0.0
        while not bot.is_closed():
            await _post_stats_once(bot)
            now = time.monotonic()
            if _clean_env("DISCORDBOTLIST_TOKEN") and now >= next_command_sync:
                await _sync_discordbotlist_commands(bot)
                next_command_sync = now + _COMMAND_SYNC_INTERVAL_SECONDS
            await asyncio.sleep(_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Le worker d'annuaires SentriX s'est arrêté de façon inattendue.")


async def directory_status(request: web.Request) -> web.Response:
    """Diagnostic sans secret : statut uniquement, jamais le token."""
    bot = request.app["bot"]
    state = getattr(bot, "_sentrix_directory_stats", None)
    if not isinstance(state, dict):
        state = {
            "updated_at": None,
            "stats": _snapshot(bot),
            "results": {},
            "commands": {},
            "configured": {
                "topgg": bool(_clean_env("TOPGG_TOKEN")),
                "discordbotlist": bool(_clean_env("DISCORDBOTLIST_TOKEN")),
            },
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
