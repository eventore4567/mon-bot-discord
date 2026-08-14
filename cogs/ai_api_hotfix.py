"""Runtime hotfix and live diagnostics for SentriX OpenAI API compatibility.

The bot keeps its internal Luna/Terra/Sol tiers, but maps them to public OpenAI API model
IDs and sanitizes reasoning/image parameters before requests are sent. Diagnostics never
expose credentials, prompts from users, or raw provider errors.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time

import discord
from aiohttp import web
from discord.ext import commands

import config
from utils import ai_api_compat

logger = logging.getLogger("bot.ai-api-hotfix")
_SHARED_RUNTIME_PREFIX = "sentrix:v177:ai-runtime:"
_NATURAL_TRIGGER = re.compile(r"^(?:sentrix|ssentrix|sentri|snetri|snentrix)\b", re.IGNORECASE)


def _safe_probe(result: dict | None) -> dict | None:
    if not isinstance(result, dict):
        return None
    return {
        "status": "ok" if result.get("ok") else "error",
        "has_key": bool(result.get("has_key")),
        "error_type": None if result.get("ok") else (result.get("error_type") or "unknown"),
        "latency_ms": int(result.get("latency_ms") or 0),
    }


def _discord_path_state(bot: commands.Bot) -> dict:
    state = getattr(bot, "ai_api_hotfix_state", None)
    if not isinstance(state, dict):
        return {}
    path = state.get("discord_path")
    if not isinstance(path, dict):
        path = {}
        state["discord_path"] = path
    return path


def _mark_discord_path(bot: commands.Bot, key: str, value=None) -> None:
    path = _discord_path_state(bot)
    if not path:
        return
    path[key] = int(time.time()) if value is None else value


async def _publish_runtime_heartbeat(bot: commands.Bot) -> None:
    """Publish a short-lived, secret-free state so sibling Railway services can be compared."""
    state = getattr(bot, "ai_api_hotfix_state", None)
    if not isinstance(state, dict):
        return
    infra = getattr(bot, "sentrix_infra", None)
    redis = getattr(infra, "redis", None)
    if redis is None:
        return

    service = str(state.get("railway_service") or "unknown")[:120]
    bot_user = getattr(bot, "user", None)
    payload = {
        "service": service,
        "service_id": state.get("railway_service_id"),
        "bot_user_id": str(getattr(bot_user, "id", "")) or None,
        "bot_user_name": str(bot_user)[:120] if bot_user is not None else None,
        "key_configured": bool(state.get("has_key")),
        "fast_model": state.get("fast_model"),
        "probe": state.get("probe"),
        "generation_probe": state.get("generation_probe"),
        "ai_cog_loaded": bool(state.get("ai_cog_loaded")),
        "natural_fallback_registered": bool(state.get("natural_fallback_registered")),
        "discord_path": state.get("discord_path"),
        "updated_at": int(time.time()),
    }
    try:
        await redis.set(
            f"{_SHARED_RUNTIME_PREFIX}{service}",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            ex=900,
        )
    except Exception:
        logger.debug("Unable to publish shared AI runtime heartbeat.", exc_info=True)


async def _heartbeat_loop(bot: commands.Bot) -> None:
    await bot.wait_until_ready()
    while not bot.is_closed():
        await _publish_runtime_heartbeat(bot)
        await asyncio.sleep(60)


async def _probe_openai_after_ready(bot: commands.Bot) -> None:
    """Probe both raw connectivity and the exact text-generation path used by SentriX."""
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

    generation_started = time.monotonic()
    try:
        generated = await asyncio.wait_for(
            ai_service.generate(
                "Réponds uniquement par le mot : ok",
                model_key=ai_service.MODEL_LUNA,
                reasoning_effort="none",
                instructions=ai_service.SYSTEM_PROMPT,
                command="live-full-path-probe",
                web_search=False,
            ),
            timeout=25,
        )
        generation_probe = {
            "status": "ok" if generated.ok and bool((generated.text or "").strip()) else "error",
            "error_code": None if generated.ok else generated.error,
            "empty_response": bool(generated.ok and not (generated.text or "").strip()),
            "latency_ms": int((time.monotonic() - generation_started) * 1000),
            "model": ai_service.MODEL_IDS.get(ai_service.MODEL_LUNA),
        }
    except Exception as exc:
        generation_probe = {
            "status": "error",
            "error_code": type(exc).__name__,
            "empty_response": False,
            "latency_ms": int((time.monotonic() - generation_started) * 1000),
            "model": ai_service.MODEL_IDS.get(ai_service.MODEL_LUNA),
        }

    state = getattr(bot, "ai_api_hotfix_state", None)
    if isinstance(state, dict):
        state["probe"] = probe
        state["generation_probe"] = generation_probe
        state["probe_updated_at"] = int(time.time())

    await _publish_runtime_heartbeat(bot)

    if probe and probe.get("status") == "ok" and generation_probe.get("status") == "ok":
        logger.info(
            "SentriX AI live probes: connectivity OK (%sms), full generation OK (%sms).",
            probe.get("latency_ms"), generation_probe.get("latency_ms"),
        )
    else:
        logger.error(
            "SentriX AI live probes failed: connectivity=%s full_generation=%s",
            probe, generation_probe,
        )


def _install_natural_message_fallback(bot: commands.Bot) -> None:
    """Self-heal plain `sentrix ...` messages if the primary Ai cog listener stays silent.

    The fallback waits briefly and only answers when the normal listener has not entered
    send_sentrix_reply(). It therefore does not duplicate healthy replies. It also supports
    DMs, which the legacy listener intentionally ignored.
    """
    if getattr(bot, "_sentrix_natural_fallback_installed", False):
        return

    ai_cog = bot.get_cog("Ai")
    state = getattr(bot, "ai_api_hotfix_state", None)
    if isinstance(state, dict):
        state["ai_cog_loaded"] = ai_cog is not None

    started_messages: set[int] = set()

    if ai_cog is not None:
        original_send = ai_cog.send_sentrix_reply
        if not getattr(original_send, "_sentrix_natural_tracked", False):
            async def tracked_send(destination, author, question: str, *, reply_to=None):
                message_id = getattr(reply_to, "id", None)
                if message_id is not None:
                    started_messages.add(int(message_id))
                    _mark_discord_path(bot, "primary_started_at")
                    _mark_discord_path(bot, "last_message_id", str(message_id))
                try:
                    result = await original_send(
                        destination,
                        author,
                        question,
                        reply_to=reply_to,
                    )
                    if message_id is not None:
                        _mark_discord_path(bot, "reply_completed_at")
                        _mark_discord_path(bot, "last_error", None)
                    return result
                except Exception as exc:
                    if message_id is not None:
                        _mark_discord_path(bot, "last_error", type(exc).__name__)
                    raise
                finally:
                    if message_id is not None:
                        async def cleanup(mid: int):
                            await asyncio.sleep(60)
                            started_messages.discard(mid)
                        asyncio.create_task(cleanup(int(message_id)))

            tracked_send._sentrix_natural_tracked = True
            tracked_send._sentrix_original = original_send
            ai_cog.send_sentrix_reply = tracked_send

    async def fallback_on_message(message: discord.Message):
        if getattr(message.author, "bot", False):
            return
        content = (message.content or "").strip()
        if not content:
            return

        bot_user = bot.user
        mentioned = bool(bot_user is not None and bot_user in getattr(message, "mentions", []))
        name_match = _NATURAL_TRIGGER.match(content)
        if not mentioned and name_match is None:
            return

        _mark_discord_path(bot, "trigger_seen_at")
        _mark_discord_path(bot, "last_message_id", str(message.id))
        _mark_discord_path(bot, "last_error", None)

        guild = getattr(message, "guild", None)
        if guild is not None and hasattr(bot, "prefix_cache"):
            prefix = bot.prefix_cache.get(guild.id, config.DEFAULT_PREFIX)
        else:
            prefix = config.DEFAULT_PREFIX
        if prefix and content.startswith(prefix):
            return

        question = content
        if mentioned:
            question = re.sub(r"<@!?\d+>", "", question, count=1).strip()
        elif name_match is not None:
            question = content[name_match.end():].lstrip(" ,:-").strip()
        if not question:
            question = "Salut, comment tu vas ?"

        current_ai_cog = bot.get_cog("Ai")
        if current_ai_cog is not None and guild is not None:
            try:
                command_line = current_ai_cog._natural_command_line(
                    question,
                    prefix,
                    has_attachment=bool(getattr(message, "attachments", [])),
                )
                if command_line:
                    _mark_discord_path(bot, "natural_command_detected_at")
                    return
            except Exception:
                logger.debug("Natural command pre-check failed; continuing to AI fallback.", exc_info=True)

        # The healthy primary listener reaches send_sentrix_reply almost immediately.
        # Give it enough time to mark this message before taking over.
        await asyncio.sleep(1.0)
        if int(message.id) in started_messages:
            return

        _mark_discord_path(bot, "fallback_used_at")
        current_ai_cog = bot.get_cog("Ai")
        try:
            async with message.channel.typing():
                if current_ai_cog is not None:
                    await current_ai_cog.send_sentrix_reply(
                        message.channel,
                        message.author,
                        question,
                        reply_to=message,
                    )
                else:
                    # Last-resort path if the Ai cog failed to load: still answer through
                    # the already-probed central AI service instead of leaving total silence.
                    from utils import ai_service
                    result = await ai_service.generate(
                        question,
                        model_key=ai_service.MODEL_LUNA,
                        reasoning_effort="none",
                        instructions=ai_service.SYSTEM_PROMPT,
                        guild_id=getattr(guild, "id", None),
                        channel_id=getattr(message.channel, "id", None),
                        user_id=getattr(message.author, "id", None),
                        command="sentrix-natural-fallback",
                        web_search=ai_service.needs_web_search(question),
                    )
                    if result.ok:
                        text = (result.text or "…").strip()
                    else:
                        text = ai_service.error_message(result.error)
                    try:
                        await message.reply(text[:2000], mention_author=True)
                    except discord.HTTPException:
                        await message.channel.send(text[:2000])
            _mark_discord_path(bot, "fallback_completed_at")
            _mark_discord_path(bot, "last_error", None)
        except Exception as exc:
            _mark_discord_path(bot, "last_error", type(exc).__name__)
            logger.exception("SentriX natural-message fallback failed.")
        finally:
            await _publish_runtime_heartbeat(bot)

    bot.add_listener(fallback_on_message, "on_message")
    bot._sentrix_natural_fallback_listener = fallback_on_message
    bot._sentrix_natural_fallback_installed = True
    if isinstance(state, dict):
        state["natural_fallback_registered"] = True


def _install_safe_health_patch(bot: commands.Bot) -> None:
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
        ai_payload = {
            "key_configured": bool(state.get("has_key")) if isinstance(state, dict) else False,
            "fast_model": state.get("fast_model") if isinstance(state, dict) else None,
            "balanced_model": state.get("balanced_model") if isinstance(state, dict) else None,
            "advanced_model": state.get("advanced_model") if isinstance(state, dict) else None,
            "image_model": state.get("image_model") if isinstance(state, dict) else None,
            "probe": state.get("probe") if isinstance(state, dict) else None,
            "generation_probe": state.get("generation_probe") if isinstance(state, dict) else None,
            "discord_path": state.get("discord_path") if isinstance(state, dict) else None,
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
    ai_service.IMAGE_SIZE_4K = ai_api_compat.IMAGE_API_SIZE

    current_pick = ai_service.pick_reasoning_effort
    if not getattr(current_pick, "_sentrix_api_compat", False):
        def safe_pick_reasoning_effort(model_key: str, base_effort: str = "medium") -> str:
            return ai_api_compat.compatible_reasoning(model_key, base_effort)

        safe_pick_reasoning_effort._sentrix_api_compat = True
        safe_pick_reasoning_effort._sentrix_original = current_pick
        ai_service.pick_reasoning_effort = safe_pick_reasoning_effort

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
        "railway_service": os.getenv("RAILWAY_SERVICE_NAME") or "unknown",
        "railway_service_id": os.getenv("RAILWAY_SERVICE_ID") or None,
        "probe": None,
        "generation_probe": None,
        "probe_updated_at": None,
        "ai_cog_loaded": False,
        "natural_fallback_registered": False,
        "discord_path": {
            "trigger_seen_at": None,
            "primary_started_at": None,
            "fallback_used_at": None,
            "reply_completed_at": None,
            "fallback_completed_at": None,
            "natural_command_detected_at": None,
            "last_message_id": None,
            "last_error": None,
        },
    }

    _install_natural_message_fallback(bot)
    _install_safe_health_patch(bot)
    task = getattr(bot, "_sentrix_ai_startup_probe_task", None)
    if task is None or task.done():
        bot._sentrix_ai_startup_probe_task = asyncio.create_task(_probe_openai_after_ready(bot))
    heartbeat = getattr(bot, "_sentrix_ai_heartbeat_task", None)
    if heartbeat is None or heartbeat.done():
        bot._sentrix_ai_heartbeat_task = asyncio.create_task(_heartbeat_loop(bot))

    if not bot.ai_api_hotfix_state["has_key"]:
        logger.error("SentriX AI: OPENAI_API_KEY is missing; AI commands cannot call OpenAI.")
    else:
        logger.info(
            "SentriX AI API compatibility active: service=%s fast=%s balanced=%s advanced=%s image=%s fallback=%s",
            bot.ai_api_hotfix_state["railway_service"],
            fast_model,
            balanced_model,
            advanced_model,
            image_model,
            bot.ai_api_hotfix_state["natural_fallback_registered"],
        )
