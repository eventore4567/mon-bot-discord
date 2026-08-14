"""Renforce /health pour une surveillance externe réelle de SentriX."""
from __future__ import annotations

import json
import time

from aiohttp import web

from .production_observability import build_runtime_snapshot

_INSTALLED = False
_SHARED_RUNTIME_PREFIX = "sentrix:v177:ai-runtime:"


def _safe_discord_path(path) -> dict | None:
    if not isinstance(path, dict):
        return None
    return {
        "trigger_seen_at": path.get("trigger_seen_at"),
        "primary_started_at": path.get("primary_started_at"),
        "fallback_used_at": path.get("fallback_used_at"),
        "reply_completed_at": path.get("reply_completed_at"),
        "fallback_completed_at": path.get("fallback_completed_at"),
        "natural_command_detected_at": path.get("natural_command_detected_at"),
        "recovery_trigger_seen_at": path.get("recovery_trigger_seen_at"),
        "recovery_primary_entered_at": path.get("recovery_primary_entered_at"),
        "recovery_used_at": path.get("recovery_used_at"),
        "recovery_completed_at": path.get("recovery_completed_at"),
        "reply_recovery_registered": bool(path.get("reply_recovery_registered")),
        "last_error": path.get("last_error"),
        "last_error_stage": path.get("last_error_stage"),
        "last_error_key": path.get("last_error_key"),
    }


def _safe_ai_health(bot) -> dict:
    """Expose uniquement l'état IA utile au diagnostic, jamais une clé ou un secret."""
    state = getattr(bot, "ai_api_hotfix_state", None)
    loaded = isinstance(state, dict)
    state = state if loaded else {}

    probe = state.get("probe") if isinstance(state.get("probe"), dict) else None
    generation_probe = state.get("generation_probe") if isinstance(state.get("generation_probe"), dict) else None
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
    if isinstance(generation_probe, dict):
        generation_probe = {
            "status": generation_probe.get("status") or "error",
            "error_code": generation_probe.get("error_code"),
            "empty_response": bool(generation_probe.get("empty_response")),
            "latency_ms": int(generation_probe.get("latency_ms") or 0),
            "model": generation_probe.get("model"),
        }

    bot_user = getattr(bot, "user", None)
    return {
        "runtime_loaded": loaded,
        "key_configured": bool(state.get("has_key")),
        "railway_service": state.get("railway_service"),
        "railway_service_id": state.get("railway_service_id"),
        "bot_user_id": str(getattr(bot_user, "id", "")) or None,
        "bot_user_name": str(bot_user)[:120] if bot_user is not None else None,
        "ai_cog_loaded": bool(state.get("ai_cog_loaded")),
        "natural_fallback_registered": bool(state.get("natural_fallback_registered")),
        "reply_recovery_installed": bool(getattr(bot, "_sentrix_reply_recovery_installed", False)),
        "discord_path": _safe_discord_path(state.get("discord_path")),
        "fast_model": state.get("fast_model"),
        "balanced_model": state.get("balanced_model"),
        "advanced_model": state.get("advanced_model"),
        "image_model": state.get("image_model"),
        "probe": probe,
        "generation_probe": generation_probe,
        "probe_updated_at": state.get("probe_updated_at"),
    }


async def _shared_ai_runtimes(bot) -> list[dict]:
    """Collect secret-free sibling service heartbeats when Railway services share Redis."""
    infra = getattr(bot, "sentrix_infra", None)
    redis = getattr(infra, "redis", None)
    if redis is None:
        return []

    runtimes: list[dict] = []
    now = int(time.time())
    try:
        async for key in redis.scan_iter(match=f"{_SHARED_RUNTIME_PREFIX}*", count=20):
            raw = await redis.get(key)
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except Exception:
                continue
            if not isinstance(item, dict):
                continue
            updated_at = int(item.get("updated_at") or 0)
            if updated_at and now - updated_at > 900:
                continue
            probe = item.get("probe") if isinstance(item.get("probe"), dict) else None
            generation = item.get("generation_probe") if isinstance(item.get("generation_probe"), dict) else None
            runtimes.append({
                "service": str(item.get("service") or "unknown")[:120],
                "service_id": item.get("service_id"),
                "bot_user_id": item.get("bot_user_id"),
                "bot_user_name": str(item.get("bot_user_name"))[:120] if item.get("bot_user_name") else None,
                "key_configured": bool(item.get("key_configured")),
                "fast_model": item.get("fast_model"),
                "probe_status": probe.get("status") if probe else None,
                "probe_error_type": probe.get("error_type") if probe else None,
                "generation_status": generation.get("status") if generation else None,
                "generation_error_code": generation.get("error_code") if generation else None,
                "generation_latency_ms": int(generation.get("latency_ms") or 0) if generation else 0,
                "ai_cog_loaded": bool(item.get("ai_cog_loaded")),
                "natural_fallback_registered": bool(item.get("natural_fallback_registered")),
                "discord_path": _safe_discord_path(item.get("discord_path")),
                "updated_at": updated_at,
            })
    except Exception:
        return []
    return sorted(runtimes, key=lambda item: (item.get("service") or "", item.get("bot_user_id") or ""))[:10]


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
            "ai_instances": await _shared_ai_runtimes(bot),
        }
        if isinstance(production_v9, dict):
            payload["production_v9"] = production_v9
        if durable_state is not None:
            payload["durable_database"] = durable_state
        if infra_state is not None:
            payload["distributed_infra"] = infra_state
        return web.json_response(payload, status=status)

    dashboard_module.handle_health = production_health