"""Votes DiscordBotList pour SentriX V47.

Le webhook reste la méthode principale. Si DISCORDBOTLIST_TOKEN est configuré, la Vote
API est aussi consultée périodiquement comme filet de sécurité afin de récupérer un vote
si le webhook n'a pas été délivré.

Le Webhook Secret est lu uniquement depuis DISCORDBOTLIST_WEBHOOK_SECRET. Le token API
est lu uniquement depuis DISCORDBOTLIST_TOKEN. Aucun secret n'est renvoyé par l'API.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hmac
import logging
import os
import time

import discord
from aiohttp import ClientSession, ClientTimeout, web

from database.db import PRIMARY_CREATOR_ID

logger = logging.getLogger("bot.dashboard.discordbotlist-vote-v47")
_INSTALLED = False
_ROUTE = "/api/discordbotlist/vote"
_VOTE_API_INTERVAL = 10 * 60
_ALLOWED_ORIGINS = {
    "https://discordbotlist.com",
    "https://www.discordbotlist.com",
}


def _secret() -> str:
    return str(os.getenv("DISCORDBOTLIST_WEBHOOK_SECRET", "") or "").strip()


def _api_token() -> str:
    return str(os.getenv("DISCORDBOTLIST_TOKEN", "") or "").strip()


def _cors_headers(request: web.Request | None = None) -> dict[str, str]:
    headers = {
        "Cache-Control": "no-store, max-age=0",
        "X-Robots-Tag": "noindex, nofollow",
    }
    if request is not None:
        origin = str(request.headers.get("Origin", "") or "").strip()
        if origin in _ALLOWED_ORIGINS:
            headers.update({
                "Access-Control-Allow-Origin": origin,
                "Vary": "Origin",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Authorization, Content-Type",
                "Access-Control-Max-Age": "600",
            })
    return headers


async def _ensure_table(bot) -> None:
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS discordbotlist_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL
        )
        """
    )
    await bot.db.execute(
        "CREATE INDEX IF NOT EXISTS idx_dbl_votes_user_time "
        "ON discordbotlist_votes(user_id, created_at)"
    )


def _authorized(request: web.Request) -> bool:
    expected = _secret()
    if not expected:
        return False
    provided = str(request.headers.get("Authorization", "") or "").strip()
    if not provided:
        return False
    return hmac.compare_digest(provided, expected)


async def _creator(bot) -> discord.User | None:
    user = bot.get_user(PRIMARY_CREATOR_ID)
    if user is not None:
        return user
    try:
        return await bot.fetch_user(PRIMARY_CREATOR_ID)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None


async def _notify_creator(
    bot,
    *,
    user_id: str,
    username: str,
    total_votes: int,
    source: str,
) -> None:
    creator = await _creator(bot)
    if creator is None:
        return
    source_text = "Webhook" if source == "webhook" else "Vote API (secours)"
    text = (
        "SentriX vient de recevoir un vote sur Discord Bot List.\n\n"
        f"Utilisateur : {username}\n"
        f"ID : {user_id}\n"
        f"Détecté via : {source_text}\n"
        f"Votes enregistrés : {total_votes}"
    )
    try:
        await creator.send(text, allowed_mentions=discord.AllowedMentions.none())
    except (discord.Forbidden, discord.HTTPException):
        logger.warning("Impossible d'envoyer le MP de vote DiscordBotList au créateur.", exc_info=True)


async def _record_vote(
    bot,
    *,
    user_id: str,
    username: str,
    is_admin: bool,
    vote_time: int,
    source: str,
) -> tuple[bool, int]:
    """Enregistre un vote une seule fois, même s'il arrive par webhook puis par l'API."""
    await _ensure_table(bot)

    # Le webhook arrive en temps réel alors que la Vote API fournit son propre timestamp.
    # Une tolérance de 5 minutes permet de reconnaître le même vote sans empêcher un
    # nouveau vote plusieurs heures plus tard.
    duplicate = await bot.db.fetchone(
        "SELECT id FROM discordbotlist_votes "
        "WHERE user_id = ? AND created_at BETWEEN ? AND ? "
        "ORDER BY created_at DESC LIMIT 1",
        (user_id, vote_time - 300, vote_time + 300),
    )
    if duplicate:
        row = await bot.db.fetchone("SELECT COUNT(*) AS n FROM discordbotlist_votes")
        return False, int(row["n"] if row else 0)

    await bot.db.execute(
        "INSERT INTO discordbotlist_votes(user_id, username, is_admin, created_at) VALUES(?, ?, ?, ?)",
        (user_id, username, 1 if is_admin else 0, vote_time),
    )
    row = await bot.db.fetchone("SELECT COUNT(*) AS n FROM discordbotlist_votes")
    total_votes = int(row["n"] if row else 0)

    logger.info(
        "Vote DiscordBotList enregistré : user_id=%s source=%s total=%s.",
        user_id,
        source,
        total_votes,
    )
    await _notify_creator(
        bot,
        user_id=user_id,
        username=username,
        total_votes=total_votes,
        source=source,
    )
    return True, total_votes


def _parse_vote_timestamp(value) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    except (TypeError, ValueError, OverflowError):
        return None


async def _sync_votes_from_api(bot) -> int:
    token = _api_token()
    if not token or not getattr(bot, "user", None) or not bot.is_ready():
        return 0

    timeout = ClientTimeout(total=15, connect=6)
    url = f"https://discordbotlist.com/api/v1/bots/{bot.user.id}/upvotes"
    try:
        async with ClientSession(timeout=timeout) as session:
            async with session.get(
                url,
                headers={
                    "Authorization": token,
                    "Accept": "application/json",
                    "User-Agent": "SentriX/1.0 discordbotlist-vote-fallback",
                },
            ) as response:
                if response.status != 200:
                    body = (await response.text())[:300]
                    logger.warning(
                        "Vote API DiscordBotList refusée : HTTP %s — %s",
                        response.status,
                        body,
                    )
                    return 0
                payload = await response.json()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Impossible de consulter la Vote API DiscordBotList.")
        return 0

    if not isinstance(payload, dict):
        return 0
    votes = payload.get("upvotes")
    if not isinstance(votes, list):
        return 0

    added = 0
    # Les plus anciens d'abord afin que les notifications restent chronologiques.
    ordered = sorted(
        (item for item in votes if isinstance(item, dict)),
        key=lambda item: str(item.get("timestamp") or ""),
    )
    for vote in ordered:
        user_id = str(vote.get("user_id") or "").strip()
        if not user_id.isdigit() or len(user_id) > 25:
            continue
        vote_time = _parse_vote_timestamp(vote.get("timestamp"))
        if vote_time is None:
            continue
        username = str(vote.get("username") or "Discord user").strip()[:100]
        try:
            inserted, _ = await _record_vote(
                bot,
                user_id=user_id,
                username=username,
                is_admin=False,
                vote_time=vote_time,
                source="api",
            )
            if inserted:
                added += 1
        except Exception:
            logger.exception("Impossible d'enregistrer un vote de secours DiscordBotList.")

    bot._sentrix_discordbotlist_vote_api = {
        "updated_at": int(time.time()),
        "recent_returned": len(ordered),
        "new_votes": added,
        "total_12h": int(payload.get("total") or 0),
    }
    return added


async def _vote_api_worker(bot) -> None:
    try:
        await bot.wait_until_ready()
        await asyncio.sleep(15)
        while not bot.is_closed():
            if _api_token():
                await _sync_votes_from_api(bot)
            await asyncio.sleep(_VOTE_API_INTERVAL)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Le worker Vote API DiscordBotList s'est arrêté.")


async def vote_preflight(request: web.Request) -> web.Response:
    """Autorise uniquement le test navigateur provenant de DiscordBotList."""
    origin = str(request.headers.get("Origin", "") or "").strip()
    if origin not in _ALLOWED_ORIGINS:
        return web.Response(status=403, headers=_cors_headers(request))
    return web.Response(status=204, headers=_cors_headers(request))


async def vote_webhook(request: web.Request) -> web.Response:
    headers = _cors_headers(request)
    if not _secret():
        return web.json_response(
            {"ok": False, "error": "webhook_not_configured"},
            status=503,
            headers=headers,
        )
    if not _authorized(request):
        return web.json_response(
            {"ok": False, "error": "unauthorized"},
            status=401,
            headers=headers,
        )

    try:
        payload = await request.json()
    except Exception:
        return web.json_response(
            {"ok": False, "error": "invalid_json"},
            status=400,
            headers=headers,
        )
    if not isinstance(payload, dict):
        return web.json_response(
            {"ok": False, "error": "invalid_payload"},
            status=400,
            headers=headers,
        )

    user_id = str(payload.get("id") or "").strip()
    username = str(payload.get("username") or "Discord user").strip()[:100]
    is_admin = bool(payload.get("admin", False))
    if not user_id.isdigit() or len(user_id) > 25:
        return web.json_response(
            {"ok": False, "error": "invalid_user_id"},
            status=400,
            headers=headers,
        )

    bot = request.app["bot"]
    try:
        inserted, _ = await _record_vote(
            bot,
            user_id=user_id,
            username=username,
            is_admin=is_admin,
            vote_time=int(time.time()),
            source="webhook",
        )
    except Exception:
        logger.exception("Impossible d'enregistrer un vote DiscordBotList.")
        return web.json_response(
            {"ok": False, "error": "storage_error"},
            status=500,
            headers=headers,
        )

    return web.json_response(
        {"ok": True, "duplicate": not inserted},
        status=200,
        headers=headers,
    )


async def vote_status(request: web.Request) -> web.Response:
    """Diagnostic sans secret pour vérifier la configuration du système de votes."""
    bot = request.app["bot"]
    return web.json_response(
        {
            "ok": True,
            "service": "discordbotlist_vote_webhook",
            "webhook_configured": bool(_secret()),
            "api_fallback_configured": bool(_api_token()),
            "method": "POST",
            "api_fallback": getattr(bot, "_sentrix_discordbotlist_vote_api", None),
        },
        headers=_cors_headers(request),
    )


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        app.router.add_get(_ROUTE, vote_status)
        app.router.add_post(_ROUTE, vote_webhook)
        app.router.add_options(_ROUTE, vote_preflight)

        async def prepare_vote_system(_app):
            try:
                await _ensure_table(bot)
            except Exception:
                logger.exception("Préparation de la table DiscordBotList votes impossible.")
            if _api_token():
                _app["sentrix_dbl_vote_api_task"] = asyncio.create_task(
                    _vote_api_worker(bot),
                    name="sentrix-dbl-vote-api-fallback",
                )
            else:
                _app["sentrix_dbl_vote_api_task"] = None

        async def stop_vote_system(_app):
            task = _app.get("sentrix_dbl_vote_api_task")
            if task is None:
                return
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        app.on_startup.append(prepare_vote_system)
        app.on_cleanup.append(stop_vote_system)
        return app

    dashboard.build_app = build_app
