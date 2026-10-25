"""Diagnostic SentriX IA : tester le VRAI modèle, jamais un modèle fixe."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cogs import ai as ai_cog
from utils import ai_service


@pytest.mark.asyncio
async def test_aidiag_uses_guild_model_and_effort(monkeypatch):
    settings = {
        "enabled": True, "default_model": ai_service.MODEL_LUNA,
        "reasoning_effort": "low", "allowed_channel_ids": [44],
        "allowed_role_ids": [],
    }
    get_settings = AsyncMock(return_value=settings)
    probe = AsyncMock(return_value={"has_key": True, "ok": True, "latency_ms": 10})
    monkeypatch.setattr(ai_service, "get_settings", get_settings)
    monkeypatch.setattr(ai_service, "test_connection", probe)
    info = await ai_cog.Ai._ai_connection_diagnostic(SimpleNamespace(bot=object()), 99, 44)
    get_settings.assert_awaited_once()
    probe.assert_awaited_once_with(model_key=ai_service.MODEL_LUNA, reasoning_effort="low")
    assert info["model_id"] == ai_service.MODEL_IDS[ai_service.MODEL_LUNA]
    assert info["enabled"] is True
    assert info["channel_allowed"] is True


@pytest.mark.asyncio
async def test_aidiag_reports_disabled_guild_and_blocked_channel_without_enabling(monkeypatch):
    get_settings = AsyncMock(return_value={
        "enabled": False, "default_model": ai_service.MODEL_SOL,
        "reasoning_effort": "high", "allowed_channel_ids": [55],
        "allowed_role_ids": [7],
    })
    probe = AsyncMock(return_value={"has_key": True, "ok": True, "latency_ms": 12})
    monkeypatch.setattr(ai_service, "get_settings", get_settings)
    monkeypatch.setattr(ai_service, "test_connection", probe)
    info = await ai_cog.Ai._ai_connection_diagnostic(SimpleNamespace(bot=object()), 99, 44)
    assert info["enabled"] is False
    assert info["channel_allowed"] is False
    assert info["role_restrictions"] is True
    assert info["role_allowed"] is False
    probe.assert_awaited_once_with(model_key=ai_service.MODEL_SOL, reasoning_effort="high")


@pytest.mark.asyncio
async def test_role_restriction_checks_actual_member_role_ids(monkeypatch):
    monkeypatch.setattr(ai_service, "get_settings", AsyncMock(return_value={
        "enabled": True, "default_model": ai_service.MODEL_LUNA,
        "reasoning_effort": "low", "allowed_role_ids": [7],
    }))
    monkeypatch.setattr(ai_service, "test_connection", AsyncMock(return_value={
        "has_key": True, "ok": True, "latency_ms": 10,
    }))
    result = await ai_cog.Ai._ai_connection_diagnostic(
        SimpleNamespace(bot=object()), 99, 44, role_ids=[7],
    )
    assert result["role_allowed"] is True


@pytest.mark.asyncio
async def test_aidiag_falls_back_to_same_model_as_generate(monkeypatch):
    monkeypatch.setattr(ai_service, "get_settings", AsyncMock(return_value={
        "enabled": True, "default_model": "unknown", "reasoning_effort": "invalid",
    }))
    probe = AsyncMock(return_value={"has_key": False, "ok": False, "latency_ms": 0})
    monkeypatch.setattr(ai_service, "test_connection", probe)
    info = await ai_cog.Ai._ai_connection_diagnostic(SimpleNamespace(bot=object()), 99, 44)
    assert info["model_key"] == ai_service.MODEL_TERRA
    probe.assert_awaited_once_with(model_key=ai_service.MODEL_TERRA, reasoning_effort="medium")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_exception,expected_code",
    [
        ("NotFoundError", ai_service.ERROR_MODEL_NOT_FOUND),
        ("PermissionDeniedError", ai_service.ERROR_MODEL_FORBIDDEN),
    ],
)
async def test_generate_reports_model_failure_instead_of_generic(monkeypatch, provider_exception, expected_code):
    import openai

    class ProviderFailure(Exception):
        pass

    monkeypatch.setattr(openai, provider_exception, ProviderFailure)
    create = AsyncMock(side_effect=ProviderFailure("do not show this provider detail"))
    monkeypatch.setattr(
        ai_service, "get_client",
        lambda: SimpleNamespace(responses=SimpleNamespace(create=create)),
    )
    result = await ai_service.generate(
        "Bonjour", model_key=ai_service.MODEL_LUNA,
        command="test", guild_id=123, user_id=42,
    )
    assert result.error == expected_code
    assert ai_service.is_error_code(result.error)
    assert "do not show" not in ai_service.error_message(result.error)
    assert "modèle" in ai_service.error_message(result.error).lower()
    assert create.await_count == 1


@pytest.mark.asyncio
async def test_connection_probe_uses_selected_model_and_reasoning(monkeypatch):
    monkeypatch.setattr(ai_service.config, "OPENAI_API_KEY", "test-not-a-real-key")
    fake_create = AsyncMock(return_value=SimpleNamespace(output_text="ok"))
    monkeypatch.setattr(
        ai_service, "get_client",
        lambda: SimpleNamespace(responses=SimpleNamespace(create=fake_create)),
    )
    result = await ai_service.test_connection(
        ai_service.MODEL_LUNA, reasoning_effort="medium",
    )
    assert result["ok"] is True
    assert fake_create.await_args.kwargs["model"] == ai_service.MODEL_IDS[ai_service.MODEL_LUNA]
    assert fake_create.await_args.kwargs["reasoning"]["effort"] == "medium"
