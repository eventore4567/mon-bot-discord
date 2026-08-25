"""Credential-free regression gate for SentriX AI API compatibility.

The gate validates the compatibility contract rather than pinning historical model names.
Exact defaults live in utils.ai_api_compat; this test verifies migration, operator override
preservation and reasoning normalization without turning an old hotfix into a false red CI.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.ai_api_compat import (
    ADVANCED_MODEL_FALLBACK,
    BALANCED_MODEL_FALLBACK,
    FAST_MODEL_FALLBACK,
    IMAGE_API_SIZE,
    IMAGE_MODEL_FALLBACK,
    compatible_model,
    compatible_reasoning,
)


def main() -> None:
    for value in (
        FAST_MODEL_FALLBACK,
        BALANCED_MODEL_FALLBACK,
        ADVANCED_MODEL_FALLBACK,
        IMAGE_MODEL_FALLBACK,
    ):
        assert isinstance(value, str) and value.strip()
    assert len({FAST_MODEL_FALLBACK, BALANCED_MODEL_FALLBACK, ADVANCED_MODEL_FALLBACK}) == 3
    assert IMAGE_API_SIZE in {"1024x1024", "1024x1536", "1536x1024", "auto"}

    # Empty values use the configured current fallback.
    assert compatible_model(None, FAST_MODEL_FALLBACK) == FAST_MODEL_FALLBACK
    assert compatible_model("", BALANCED_MODEL_FALLBACK) == BALANCED_MODEL_FALLBACK
    # Historical SentriX defaults migrate to the current tier selected by the module.
    assert compatible_model("gpt-5-mini", FAST_MODEL_FALLBACK) == FAST_MODEL_FALLBACK
    assert compatible_model("gpt-5.1", BALANCED_MODEL_FALLBACK) == BALANCED_MODEL_FALLBACK
    assert compatible_model("gpt-5-pro", ADVANCED_MODEL_FALLBACK) == ADVANCED_MODEL_FALLBACK
    assert compatible_model("gpt-image-1", IMAGE_MODEL_FALLBACK, image=True) == IMAGE_MODEL_FALLBACK
    # A genuine operator override must never be silently rewritten.
    assert compatible_model("custom-model", FAST_MODEL_FALLBACK) == "custom-model"

    assert compatible_reasoning("luna", "none") == "none"
    assert compatible_reasoning("luna", "low") == "low"
    assert compatible_reasoning("luna", "invalid") == "none"
    assert compatible_reasoning("terra", "invalid") == "low"
    assert compatible_reasoning("terra", "none") == "none"
    assert compatible_reasoning("sol", "none") == "high"
    assert compatible_reasoning("sol", "xhigh") == "xhigh"
    assert compatible_reasoning("sol", "max") == "max"

    loader_text = (ROOT / "cogs" / "remove_code_command" / "__init__.py").read_text(encoding="utf-8")
    hotfix_text = (ROOT / "cogs" / "ai_api_hotfix.py").read_text(encoding="utf-8")
    assert "install_ai_api_hotfix" in loader_text
    assert "await install_ai_api_hotfix(bot)" in loader_text
    assert "ai_service.IMAGE_SIZE_4K = ai_api_compat.IMAGE_API_SIZE" in hotfix_text
    assert "compatible_reasoning" in hotfix_text
    assert "OPENAI_API_KEY is missing" in hotfix_text

    print("SentriX AI compatibility gate: OK (current routing contract, legacy migration, overrides preserved)")


if __name__ == "__main__":
    main()
