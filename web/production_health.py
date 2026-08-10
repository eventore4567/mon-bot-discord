"""Renforce /health pour une surveillance externe réelle de SentriX."""
from __future__ import annotations

import time

from aiohttp import web

_INSTALLED = False


def install(dashboard_module) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    async def production_health(request: web.Request):
        bot = request.app["bot"]
        discord_ready = bool(bot.is_ready())
        db_ok = getattr(getattr(bot, "db", None), "_conn", None) is not None
        if db_ok:
            try:
                row = await bot.db.fetchone("SELECT 1 AS ok")
                db_ok = bool(row and int(row["ok"]) == 1)
            except Exception:
                db_ok = False

        durable_state = None
        durable = getattr(bot, "sentrix_durable_store", None)
        if durable is not None and hasattr(durable, "health"):
            try:
                durable_state = await durable.health()
            except Exception as exc:
                durable_state = {"configured": bool(getattr(durable, "configured", False)), "postgres_online": False, "error": str(exc)[:300]}

        infra_state = None
        infra = getattr(bot, "sentrix_infra", None)
        if infra is not None and hasattr(infra, "health"):
            try:
                infra_state = await infra.health()
            except Exception as exc:
                infra_state = {"postgres_online": False, "redis_online": False, "error": str(exc)[:300]}

        uptime = int(time.time() - dashboard_module.START_TIME)
        # Le dashboard se lie volontairement avant Discord. Durant les 90 premières
        # secondes, HTTP reste 200 pour ne pas transformer un déploiement normal en panne,
        # mais discord_ready=false permet au moniteur externe de patienter/retester.
        healthy = db_ok and discord_ready
        status = 200 if healthy or uptime < 90 else 503
        payload = {
            "ok": healthy,
            "discord_ready": discord_ready,
            "database_ok": db_ok,
            "latency_ms": round(bot.latency * 1000) if discord_ready else None,
            "uptime_seconds": uptime,
            "shards": int(getattr(bot, "shard_count", 1) or 1),
        }
        if durable_state is not None:
            payload["durable_database"] = durable_state
        if infra_state is not None:
            payload["distributed_infra"] = infra_state
        return web.json_response(payload, status=status)

    dashboard_module.handle_health = production_health
