"""Compatibility rules for SentriX OpenAI API model routing.

This module deliberately contains no Discord/OpenAI imports so its behavior can be tested
in CI without credentials or network access.
"""
from __future__ import annotations

FAST_MODEL_FALLBACK = "gpt-5-mini"
BALANCED_MODEL_FALLBACK = "gpt-5.1"
ADVANCED_MODEL_FALLBACK = "gpt-5-pro"
IMAGE_MODEL_FALLBACK = "gpt-image-1"
IMAGE_API_SIZE = "1536x1024"

# IDs that were previously used by SentriX but are not public OpenAI API model IDs.
_KNOWN_BAD_TEXT_MODELS = {
    "gpt-5.6-luna",
    "gpt-5.6-terra",
    "gpt-5.6-sol",
}
_KNOWN_BAD_IMAGE_MODELS = {"gpt-image-2"}


def compatible_model(configured: str | None, fallback: str, *, image: bool = False) -> str:
    """Keep a custom model override unless it is empty or a known invalid SentriX default."""
    value = str(configured or "").strip()
    bad = _KNOWN_BAD_IMAGE_MODELS if image else _KNOWN_BAD_TEXT_MODELS
    if not value or value.casefold() in bad:
        return fallback
    return value


def compatible_reasoning(model_key: str, requested: str | None) -> str:
    """Return a reasoning effort accepted by the API model family used for each SentriX tier.

    Internal tier names stay stable (luna/terra/sol), while their API model IDs can change.
    - Luna -> GPT-5 mini: minimal/low/medium/high (not none).
    - Terra -> GPT-5.1: none/low/medium/high.
    - Sol -> GPT-5 pro: high only.
    """
    effort = str(requested or "").strip().lower()
    if model_key == "sol":
        return "high"
    if model_key == "terra":
        return effort if effort in {"none", "low", "medium", "high"} else "low"
    return effort if effort in {"minimal", "low", "medium", "high"} else "minimal"
