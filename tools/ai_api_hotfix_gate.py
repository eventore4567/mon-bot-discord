"""Credential-free regression gate for SentriX AI API compatibility."""
from pathlib import Path

from utils.ai_api_compat import (
    ADVANCED_MODEL_FALLBACK,
    BALANCED_MODEL_FALLBACK,
    FAST_MODEL_FALLBACK,
    IMAGE_API_SIZE,
    IMAGE_MODEL_FALLBACK,
    compatible_model,
    compatible_reasoning,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    assert FAST_MODEL_FALLBACK == "gpt-5-mini"
    assert BALANCED_MODEL_FALLBACK == "gpt-5.1"
    assert ADVANCED_MODEL_FALLBACK == "gpt-5-pro"
    assert IMAGE_MODEL_FALLBACK == "gpt-image-1"
    assert IMAGE_API_SIZE in {"1024x1024", "1024x1536", "1536x1024", "auto"}

    assert compatible_model("gpt-5.6-luna", FAST_MODEL_FALLBACK) == FAST_MODEL_FALLBACK
    assert compatible_model("gpt-5.6-terra", BALANCED_MODEL_FALLBACK) == BALANCED_MODEL_FALLBACK
    assert compatible_model("gpt-5.6-sol", ADVANCED_MODEL_FALLBACK) == ADVANCED_MODEL_FALLBACK
    assert compatible_model("gpt-image-2", IMAGE_MODEL_FALLBACK, image=True) == IMAGE_MODEL_FALLBACK
    assert compatible_model("custom-model", FAST_MODEL_FALLBACK) == "custom-model"

    assert compatible_reasoning("luna", "none") == "minimal"
    assert compatible_reasoning("luna", "low") == "low"
    assert compatible_reasoning("terra", "minimal") == "low"
    assert compatible_reasoning("terra", "none") == "none"
    assert compatible_reasoning("sol", "none") == "high"
    assert compatible_reasoning("sol", "xhigh") == "high"

    config_text = (ROOT / "config.py").read_text(encoding="utf-8")
    env_text = (ROOT / ".env.example").read_text(encoding="utf-8")
    loader_text = (ROOT / "cogs" / "remove_code_command" / "__init__.py").read_text(encoding="utf-8")
    hotfix_text = (ROOT / "cogs" / "ai_api_hotfix.py").read_text(encoding="utf-8")

    for bad in ("gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol", "gpt-image-2"):
        assert bad not in config_text, f"invalid API default still present in config.py: {bad}"
        assert bad not in env_text, f"invalid API example still present in .env.example: {bad}"

    assert "install_ai_api_hotfix" in loader_text
    assert "await install_ai_api_hotfix(bot)" in loader_text
    assert "ai_service.IMAGE_SIZE_4K = ai_api_compat.IMAGE_API_SIZE" in hotfix_text
    assert "compatible_reasoning" in hotfix_text
    assert "OPENAI_API_KEY is missing" in hotfix_text

    print("SentriX AI API hotfix gate: OK")


if __name__ == "__main__":
    main()
