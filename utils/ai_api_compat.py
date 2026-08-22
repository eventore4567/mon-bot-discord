"""Compatibility rules for SentriX OpenAI API model routing.

SentriX keeps the internal Luna/Terra/Sol tier names, but these tiers now map directly to
OpenAI's current GPT-5.6 API models. Older SentriX defaults are upgraded automatically so
an existing Railway deployment does not stay pinned to the pre-5.6 routing by accident.

This module deliberately contains no Discord/OpenAI imports so its behavior remains easy
to test in CI without credentials or network access.
"""
from __future__ import annotations

FAST_MODEL_FALLBACK = "gpt-5.6-luna"
BALANCED_MODEL_FALLBACK = "gpt-5.6-terra"
ADVANCED_MODEL_FALLBACK = "gpt-5.6-sol"
IMAGE_MODEL_FALLBACK = "gpt-image-2"
IMAGE_API_SIZE = "1536x1024"

# Defaults previously shipped by SentriX itself. Treat these as migration aliases rather
# than intentional custom overrides. A genuinely different model supplied by the operator
# is still preserved unchanged.
_LEGACY_TEXT_DEFAULTS = {
    "gpt-5-mini": FAST_MODEL_FALLBACK,
    "gpt-5.1": BALANCED_MODEL_FALLBACK,
    "gpt-5-pro": ADVANCED_MODEL_FALLBACK,
}
_LEGACY_IMAGE_DEFAULTS = {
    "gpt-image-1": IMAGE_MODEL_FALLBACK,
}


def compatible_model(configured: str | None, fallback: str, *, image: bool = False) -> str:
    """Return a current model ID while preserving genuine operator overrides."""
    value = str(configured or "").strip()
    if not value:
        return fallback

    if image:
        return _LEGACY_IMAGE_DEFAULTS.get(value.casefold(), value)
    return _LEGACY_TEXT_DEFAULTS.get(value.casefold(), value)


def compatible_reasoning(model_key: str, requested: str | None) -> str:
    """Normalize reasoning effort for the GPT-5.6 tier used by SentriX.

    Luna is optimized for the fast/high-volume path, so an invalid setting falls back to
    ``none``. Terra keeps a small amount of reasoning by default. Sol remains reserved for
    the difficult path and therefore never silently drops below ``high``.
    """
    effort = str(requested or "").strip().lower()
    allowed = {"none", "low", "medium", "high", "xhigh", "max"}

    if model_key == "sol":
        return effort if effort in {"high", "xhigh", "max"} else "high"
    if model_key == "terra":
        return effort if effort in allowed else "low"
    return effort if effort in allowed else "none"
