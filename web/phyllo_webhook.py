"""Webhook public Phyllo pour les notifications sociales SentriX."""
from __future__ import annotations

import json
import logging
import os
import time

from aiohttp import web

from services import social_providers


logger = logging.getLogger("bot.phyllo-webhook")


def _secret() -> str:
    return os.getenv("PHYLLO_WEBHOOK_SECRET", "").strip()


async def handle_phyllo_webhook(request: web.Request) -> web.Response:
    secret = _secret()
    if not secret:
        return web.json_response(
            {"ok": False, "error": "phyllo_not_configured"},
            status=503,
        )

    try:
        raw = await request.read()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_body"}, status=400)

    signature = request.headers.get("X-Phyllo-Signature", "")
    if not social_providers.verify_phyllo_signature(raw, signature, secret):
        logger.warning("Webhook Phyllo rejeté : signature invalide.")
        return web.json_response({"ok": False, "error": "invalid_signature"}, status=401)

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
    if not isinstance(payload, dict):
        return web.json_response({"ok": False, "error": "invalid_payload"}, status=400)

    event_key = social_providers.webhook_event_key(payload, raw)
    bot = request.app["bot"]

    # Déduplication durable : Phyllo peut retenter un webhook après timeout/5xx.
    try:
        existing = await bot.db.fetchone(
            "SELECT event_key FROM social_webhook_events WHERE event_key=?",
            (event_key,),
        )
    except Exception:
        logger.exception("Impossible de lire la déduplication webhook Phyllo.")
        return web.json_response({"ok": False, "error": "storage_unavailable"}, status=503)

    if existing:
        return web.json_response({"ok": True, "duplicate": True, "delivered": 0})

    cog = bot.get_cog("Notifications")
    if cog is None:
        return web.json_response(
            {"ok": False, "error": "notifications_unavailable"},
            status=503,
        )

    try:
        delivered = await cog.handle_provider_webhook(payload, provider="phyllo")
    except Exception:
        logger.exception("Traitement webhook Phyllo impossible.")
        # 5xx volontaire : Phyllo pourra retenter.
        return web.json_response({"ok": False, "error": "processing_failed"}, status=503)

    await bot.db.execute(
        "INSERT INTO social_webhook_events (event_key,provider,received_at) VALUES (?,?,?)",
        (event_key, "phyllo", int(time.time())),
    )
    return web.json_response(
        {
            "ok": True,
            "provider": "phyllo",
            "delivered": int(delivered),
        }
    )


def register(app: web.Application, dashboard) -> None:
    del dashboard
    app.router.add_post("/api/webhooks/phyllo", handle_phyllo_webhook)


__all__ = ["handle_phyllo_webhook", "register"]
