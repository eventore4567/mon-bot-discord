"""Rapports de bug / avis du dashboard SentriX.

Stockage minimal : auteur Discord authentifié, serveur géré, page/onglet, commentaire,
détail technique facultatif et release serveur. Aucun IP, cookie, token OAuth ou
contenu Discord privé n'est enregistré.
"""
from __future__ import annotations

import json
import logging
import os
import time

from aiohttp import web

logger = logging.getLogger("bot.dashboard-feedback")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dashboard_feedback_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    page TEXT NOT NULL DEFAULT '',
    tab TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL,
    technical TEXT NOT NULL DEFAULT '',
    release TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    created_at INTEGER NOT NULL
)
"""

_ALLOWED_KINDS = {"bug", "feedback"}


def _clean(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


async def _ensure_schema(bot) -> None:
    await bot.db.execute(_SCHEMA)


def register(app: web.Application, dashboard) -> None:
    async def create_report(request: web.Request) -> web.Response:
        try:
            guild_id = int(request.match_info["guild_id"])
        except (TypeError, ValueError):
            return dashboard._json_error("Serveur invalide.", 400)

        session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error

        csrf_error = dashboard._require_csrf(request, session)
        if csrf_error:
            return csrf_error

        rate_key = (
            request.cookies.get(dashboard.SESSION_COOKIE, ""),
            guild_id,
            "dashboard-feedback",
        )
        now = time.time()
        last = float(request.app["write_limits"].get(rate_key, 0) or 0)
        if now - last < 10:
            return dashboard._json_error(
                "Attends quelques secondes avant d'envoyer un autre rapport.",
                429,
            )

        try:
            payload = await request.json()
        except (json.JSONDecodeError, TypeError):
            return dashboard._json_error("Rapport invalide.", 400)

        kind = _clean(payload.get("kind"), 20).casefold()
        message = _clean(payload.get("message"), 2000)
        technical = _clean(payload.get("technical"), 1500)
        page = _clean(payload.get("page"), 120)
        tab = _clean(payload.get("tab"), 64)

        if kind not in _ALLOWED_KINDS:
            return dashboard._json_error("Choisis Bug ou Avis.", 400)
        if len(message) < 5:
            return dashboard._json_error("Décris le problème ou ton avis.", 400)

        bot = request.app["bot"]
        await _ensure_schema(bot)
        release = _clean(
            os.getenv("RAILWAY_GIT_COMMIT_SHA")
            or os.getenv("GIT_COMMIT")
            or "",
            64,
        )
        cursor = await bot.db.execute(
            """
            INSERT INTO dashboard_feedback_reports (
                guild_id, user_id, kind, page, tab, message, technical,
                release, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)
            """,
            (
                guild_id,
                int(session["user"]["id"]),
                kind,
                page,
                tab,
                message,
                technical,
                release,
                int(now),
            ),
        )
        report_id = int(getattr(cursor, "lastrowid", 0) or 0)
        request.app["write_limits"][rate_key] = now

        logger.info(
            "Dashboard report #%s type=%s guild=%s user=%s page=%s tab=%s",
            report_id,
            kind,
            guild.id,
            session["user"]["id"],
            page,
            tab,
        )
        return web.json_response(
            {
                "ok": True,
                "id": report_id,
                "message": "Merci, ton rapport a bien été envoyé.",
            }
        )

    app.router.add_post(
        "/api/guilds/{guild_id}/feedback",
        create_report,
    )
