"""Webhook de votes DiscordBotList pour SentriX V47.

DiscordBotList POST les informations du votant vers l'URL configurée et envoie le
Webhook Secret dans le header Authorization. Le secret est lu uniquement depuis
DISCORDBOTLIST_WEBHOOK_SECRET et n'est jamais renvoyé par l'API.

Le bouton « Test Webhook » de DiscordBotList effectue sa requête depuis le navigateur.
Une politique CORS très limitée autorise donc uniquement discordbotlist.com à tester
ce endpoint avec Authorization + Content-Type. Les vrais votes restent protégés par le
même secret.
"""
from __future__ import annotations

import hmac
import logging
import os
import time

import discord
from aiohttp import web

from database.db import PRIMARY_CREATOR_ID

logger = logging.getLogger("bot.dashboard.discordbotlist-vote-v47")
_INSTALLED = False
_ROUTE = "/api/discordbotlist/vote"
_ALLOWED_ORIGINS = {
    "https://discordbotlist.com",
    "https://www.discordbotlist.com",
}


def _secret() -> str:
    return str(os.getenv("DISCORDBOTLIST_WEBHOOK_SECRET", "") or "").strip()


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


async def _notify_creator(bot, *, user_id: str, username: str, total_votes: int) -> None:
    creator = await _creator(bot)
    if creator is None:
        return
    text = (
        "SentriX vient de recevoir un vote sur Discord Bot List.\n\n"
        f"Utilisateur : {username}\n"
        f"ID : {user_id}\n"
        f"Votes reçus par le webhook : {total_votes}"
    )
    try:
        await creator.send(text, allowed_mentions=discord.AllowedMentions.none())
    except (discord.Forbidden, discord.HTTPException):
        logger.warning("Impossible d'envoyer le MP de vote DiscordBotList au créateur.", exc_info=True)


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
    now_value = int(time.time())
    try:
        await _ensure_table(bot)

        # DiscordBotList ou un proxy peut retenter une requête. On évite les doubles
        # notifications/insertions si le même vote est rejoué immédiatement.
        recent = await bot.db.fetchone(
            "SELECT id FROM discordbotlist_votes WHERE user_id = ? AND created_at >= ? "
            "ORDER BY created_at DESC LIMIT 1",
            (user_id, now_value - 20),
        )
        if recent:
            return web.json_response(
                {"ok": True, "duplicate": True},
                status=200,
                headers=headers,
            )

        await bot.db.execute(
            "INSERT INTO discordbotlist_votes(user_id, username, is_admin, created_at) VALUES(?, ?, ?, ?)",
            (user_id, username, 1 if is_admin else 0, now_value),
        )
        row = await bot.db.fetchone("SELECT COUNT(*) AS n FROM discordbotlist_votes")
        total_votes = int(row["n"] if row else 0)
    except Exception:
        logger.exception("Impossible d'enregistrer un vote DiscordBotList.")
        return web.json_response(
            {"ok": False, "error": "storage_error"},
            status=500,
            headers=headers,
        )

    logger.info("Vote DiscordBotList reçu pour user_id=%s.", user_id)
    await _notify_creator(bot, user_id=user_id, username=username, total_votes=total_votes)
    return web.json_response(
        {"ok": True},
        status=200,
        headers=headers,
    )


async def vote_status(request: web.Request) -> web.Response:
    """Petit diagnostic sans secret pour vérifier que la route existe."""
    return web.json_response(
        {
            "ok": True,
            "service": "discordbotlist_vote_webhook",
            "configured": bool(_secret()),
            "method": "POST",
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

        async def prepare_vote_table(_app):
            try:
                await _ensure_table(bot)
            except Exception:
                logger.exception("Préparation de la table DiscordBotList votes impossible.")

        app.on_startup.append(prepare_vote_table)
        return app

    dashboard.build_app = build_app
