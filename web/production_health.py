"""Renforce /health pour une surveillance externe réelle de SentriX."""
from __future__ import annotations

import time

from aiohttp import web

from .production_observability import build_runtime_snapshot

_INSTALLED = False


def _safe_ai_health(bot) -> dict:
    """Expose uniquement l'état IA utile au diagnostic, jamais une clé ou un secret."""
    state = getattr(bot, "ai_api_hotfix_state", None)
    loaded = isinstance(state, dict)
    state = state if loaded else {}

    probe = state.get("probe") if isinstance(state.get("probe"), dict) else None
    canary = getattr(bot, "sentrix_canary_status", None)
    if isinstance(canary, dict):
        for item in canary.get("checks", []):
            if not isinstance(item, dict) or item.get("name") != "openai":
                continue
            probe = {
                "status": item.get("status") or "error",
                "has_key": bool(state.get("has_key")),
                "error_type": item.get("error") or item.get("details"),
                "latency_ms": int(item.get("latency_ms") or 0),
            }
            break

    if isinstance(probe, dict):
        probe = {
            "status": probe.get("status") or "error",
            "has_key": bool(probe.get("has_key", state.get("has_key"))),
            "error_type": probe.get("error_type"),
            "latency_ms": int(probe.get("latency_ms") or 0),
        }

    return {
        "runtime_loaded": loaded,
        "key_configured": bool(state.get("has_key")),
        "fast_model": state.get("fast_model"),
        "balanced_model": state.get("balanced_model"),
        "advanced_model": state.get("advanced_model"),
        "image_model": state.get("image_model"),
        "probe": probe,
        "probe_updated_at": state.get("probe_updated_at"),
    }


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

        runtime_observability = await build_runtime_snapshot(bot)
        production_v9 = getattr(bot, "production_v9_health_snapshot", None)
        uptime = int(time.time() - dashboard_module.START_TIME)
        # Le dashboard se lie volontairement avant Discord. Durant les 90 premières
        # secondes, HTTP reste 200 pour ne pas transformer un déploiement normal en panne,
        # mais discord_ready=false permet au moniteur externe de patienter/retester.
        healthy = db_ok and discord_ready
        status = 200 if healthy or uptime < 90 else 503
        if not healthy:
            health_level = "starting" if uptime < 90 else "unavailable"
        elif isinstance(production_v9, dict) and production_v9.get("status") == "unavailable":
            health_level = "degraded"
        elif runtime_observability.get("available") and runtime_observability.get("status") in {"degraded", "stale"}:
            health_level = "degraded"
        elif isinstance(production_v9, dict) and production_v9.get("status") == "degraded":
            health_level = "degraded"
        else:
            health_level = "healthy"

        payload = {
            "ok": healthy,
            "health_level": health_level,
            "discord_ready": discord_ready,
            "database_ok": db_ok,
            "latency_ms": round(bot.latency * 1000) if discord_ready else None,
            "uptime_seconds": uptime,
            "shards": int(getattr(bot, "shard_count", 1) or 1),
            "runtime_observability": runtime_observability,
            "ai": _safe_ai_health(bot),
        }
        if isinstance(production_v9, dict):
            payload["production_v9"] = production_v9
        if durable_state is not None:
            payload["durable_database"] = durable_state
        if infra_state is not None:
            payload["distributed_infra"] = infra_state
        return web.json_response(payload, status=status)

    dashboard_module.handle_health = production_health
