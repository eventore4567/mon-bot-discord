"""Runtime hotfix and live diagnostics for SentriX OpenAI API compatibility.

The bot keeps its internal Luna/Terra/Sol tiers, but maps them to public OpenAI API model
IDs and sanitizes reasoning/image parameters before requests are sent. It also exposes a
strictly non-secret AI health summary through the existing /health endpoint so production
can be diagnosed without Railway log access.
"""
from __future__ import annotations

import asyncio
import logging
import time

from aiohttp import web
from discord.ext import commands

import config
from utils import ai_api_compat

logger = logging.getLogger("bot.ai-api-hotfix")


def _safe_probe(result: dict | None) -> dict | None:
    """Return only non-secret fields from an OpenAI connectivity probe."""
    if not isinstance(result, dict):
        return None
    return {
        "status": "ok" if result.get("ok") else "error",
        "has_key": bool(result.get("has_key")),
        "error_type": None if result.get("ok") else (result.get("error_type") or "unknown"),
        "latency_ms": int(result.get("latency_ms") or 0),
    }


async def _probe_openai_after_ready(bot: commands.Bot) -> None:
    """Run one real production probe after Discord is ready, without exposing credentials."""
    await bot.wait_until_ready()
    await asyncio.sleep(1)
    from utils import ai_service

    try:
        result = await asyncio.wait_for(
            ai_service.test_connection(model_key=ai_service.MODEL_LUNA),
            timeout=25,
        )
        probe = _safe_probe(result)
    except Exception as exc:
        probe = {
            "status": "error",
            "has_key": bool(getattr(config, "OPENAI_API_KEY", None)),
            "error_type": type(exc).__name__,
            "latency_ms": 0,
        }

    state = getattr(bot, "ai_api_hotfix_state", None)
    if isinstance(state, dict):
        state["probe"] = probe
        state["probe_updated_at"] = int(time.time())

    if probe and probe.get("status") == "ok":
        logger.info("SentriX AI live startup probe: OK (%sms).", probe.get("latency_ms"))
    else:
        logger.error(
            "SentriX AI live startup probe: FAILED type=%s key_present=%s",
            (probe or {}).get("error_type"),
            (probe or {}).get("has_key"),
        )


def _install_safe_health_patch(bot: commands.Bot) -> None:
    """Extend the existing /health JSON with safe AI runtime state only."""
    try:
        from web import dashboard
    except Exception:
        logger.debug("SentriX AI health patch unavailable: dashboard module missing.", exc_info=True)
        return

    current = dashboard.handle_health
    if getattr(current, "_sentrix_ai_health", False):
        return

    async def handle_health_with_ai(request: web.Request):
        runtime_bot = request.app["bot"]
        state = getattr(runtime_bot, "ai_api_hotfix_state", {}) or {}
        probe = state.get("probe") if isinstance(state, dict) else None

        # V13 may already have a fresher OpenAI probe. Reuse it, but only expose safe fields.
        canary = getattr(runtime_bot, "sentrix_canary_status", {}) or {}
        checks = canary.get("checks", []) if isinstance(canary, dict) else []
        for item in checks:
            if isinstance(item, dict) and item.get("name") == "openai":
                probe = {
                    "status": item.get("status") or "error",
                    "has_key": bool(state.get("has_key")) if isinstance(state, dict) else False,
                    "error_type": item.get("error"),
                    "latency_ms": int(item.get("latency_ms") or 0),
                }
                break

        ai_payload = {
            "key_configured": bool(state.get("has_key")) if isinstance(state, dict) else False,
            "fast_model": state.get("fast_model") if isinstance(state, dict) else None,
            "balanced_model": state.get("balanced_model") if isinstance(state, dict) else None,
            "advanced_model": state.get("advanced_model") if isinstance(state, dict) else None,
            "image_model": state.get("image_model") if isinstance(state, dict) else None,
            "probe": probe,
            "probe_updated_at": state.get("probe_updated_at") if isinstance(state, dict) else None,
        }
        return web.json_response({
            "ok": True,
            "discord_ready": runtime_bot.is_ready(),
            "latency_ms": round(runtime_bot.latency * 1000) if runtime_bot.is_ready() else None,
            "ai": ai_payload,
        })

    handle_health_with_ai._sentrix_ai_health = True
    handle_health_with_ai._sentrix_original = current
    dashboard.handle_health = handle_health_with_ai


async def setup(bot: commands.Bot) -> None:
    from utils import ai_service

    fast_model = ai_api_compat.compatible_model(
        getattr(config, "OPENAI_MODEL_FAST", None), ai_api_compat.FAST_MODEL_FALLBACK
    )
    balanced_model = ai_api_compat.compatible_model(
        getattr(config, "OPENAI_MODEL", None), ai_api_compat.BALANCED_MODEL_FALLBACK
    )
    advanced_model = ai_api_compat.compatible_model(
        getattr(config, "OPENAI_MODEL_ADVANCED", None), ai_api_compat.ADVANCED_MODEL_FALLBACK
    )
    image_model = ai_api_compat.compatible_model(
        getattr(config, "OPENAI_IMAGE_MODEL", None), ai_api_compat.IMAGE_MODEL_FALLBACK, image=True
    )

    # Update config as well as ai_service because ai_service reads both at runtime.
    config.OPENAI_MODEL_FAST = fast_model
    config.OPENAI_MODEL = balanced_model
    config.OPENAI_MODEL_ADVANCED = advanced_model
    config.OPENAI_IMAGE_MODEL = image_model

    ai_service.MODEL_IDS[ai_service.MODEL_LUNA] = fast_model
    ai_service.MODEL_IDS[ai_service.MODEL_TERRA] = balanced_model
    ai_service.MODEL_IDS[ai_service.MODEL_SOL] = advanced_model
    ai_service.MODEL_LABELS[ai_service.MODEL_LUNA] = f"Luna ({fast_model})"
    ai_service.MODEL_LABELS[ai_service.MODEL_TERRA] = f"Terra ({balanced_model})"
    ai_service.MODEL_LABELS[ai_service.MODEL_SOL] = f"Sol ({advanced_model})"

    # The Image API does not accept 3840x2160 as a generation size. SentriX still upscales
    # the returned landscape image to its Discord 4K delivery size in cogs/ai.py.
    ai_service.IMAGE_SIZE_4K = ai_api_compat.IMAGE_API_SIZE

    current_pick = ai_service.pick_reasoning_effort
    if not getattr(current_pick, "_sentrix_api_compat", False):
        def safe_pick_reasoning_effort(model_key: str, base_effort: str = "medium") -> str:
            return ai_api_compat.compatible_reasoning(model_key, base_effort)

        safe_pick_reasoning_effort._sentrix_api_compat = True
        safe_pick_reasoning_effort._sentrix_original = current_pick
        ai_service.pick_reasoning_effort = safe_pick_reasoning_effort

    # Defense in depth: sanitize direct callers that bypass pick_reasoning_effort().
    current_generate = ai_service.generate
    if not getattr(current_generate, "_sentrix_api_compat", False):
        async def generate_compatible(*args, **kwargs):
            model_key = kwargs.get("model_key", ai_service.MODEL_TERRA)
            kwargs["reasoning_effort"] = ai_api_compat.compatible_reasoning(
                model_key, kwargs.get("reasoning_effort", "medium")
            )
            return await current_generate(*args, **kwargs)

        generate_compatible._sentrix_api_compat = True
        generate_compatible._sentrix_original = current_generate
        ai_service.generate = generate_compatible

    bot.ai_api_hotfix_state = {
        "has_key": bool(getattr(config, "OPENAI_API_KEY", None)),
        "fast_model": fast_model,
        "balanced_model": balanced_model,
        "advanced_model": advanced_model,
        "image_model": image_model,
        "image_api_size": ai_api_compat.IMAGE_API_SIZE,
        "probe": None,
        "probe_updated_at": None,
    }

    _install_safe_health_patch(bot)
    task = getattr(bot, "_sentrix_ai_startup_probe_task", None)
    if task is None or task.done():
        bot._sentrix_ai_startup_probe_task = asyncio.create_task(_probe_openai_after_ready(bot))

    if not bot.ai_api_hotfix_state["has_key"]:
        logger.error("SentriX AI: OPENAI_API_KEY is missing; AI commands cannot call OpenAI.")
    else:
        logger.info(
            "SentriX AI API compatibility active: fast=%s balanced=%s advanced=%s image=%s",
            fast_model,
            balanced_model,
            advanced_model,
            image_model,
        )
