"""Runtime hotfix for SentriX OpenAI API compatibility.

The bot keeps its internal Luna/Terra/Sol tiers, but maps them to public OpenAI API model
IDs and sanitizes reasoning/image parameters before requests are sent.
"""
from __future__ import annotations

import logging

from discord.ext import commands

import config
from utils import ai_api_compat

logger = logging.getLogger("bot.ai-api-hotfix")


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
    }

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
