from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

import sentrix_v101_command_runtime as v101


class _SetupCog:
    async def setup_wizard(self, ctx):
        return None


class _EmbedBuilder:
    async def embedconfig_addrole(self, ctx, role: str):
        return None


def _parameter(name: str, kind=inspect.Parameter.POSITIONAL_OR_KEYWORD, *, annotation=str, default=inspect.Parameter.empty):
    return inspect.Parameter(name, kind, annotation=annotation, default=default)


def test_setup_signature_never_exposes_ctx_args_kwargs():
    command = SimpleNamespace(
        callback=_SetupCog.setup_wizard,
        cog=None,
        qualified_name="setup",
        clean_params={
            "ctx": _parameter("ctx"),
            "args": _parameter("args", inspect.Parameter.VAR_POSITIONAL),
            "kwargs": _parameter("kwargs", inspect.Parameter.VAR_KEYWORD),
        },
    )

    signature, native, names = v101._build_signature(command)

    assert native is True
    assert names == ()
    assert tuple(signature.parameters) == ("interaction",)


@pytest.mark.asyncio
async def test_detached_cog_command_restores_self_and_ctx():
    cog = _EmbedBuilder()
    bot = SimpleNamespace(cogs={"EmbedBuilder": cog})
    ctx = SimpleNamespace(bot=bot)
    command = SimpleNamespace(
        callback=_EmbedBuilder.embedconfig_addrole,
        cog=None,
        qualified_name="embedconfig addrole",
        clean_params={"role": _parameter("role", annotation=str)},
    )

    args, kwargs = await v101._bind_native_arguments(
        command,
        ctx,
        ("role",),
        {"role": "staff"},
    )

    assert args == [cog, ctx, "staff"]
    assert kwargs == {}


def test_real_user_varargs_still_fall_back_to_arguments_text():
    async def legacy(ctx, *values: str):
        return None

    command = SimpleNamespace(
        callback=legacy,
        cog=None,
        qualified_name="legacy",
        clean_params={"values": _parameter("values", inspect.Parameter.VAR_POSITIONAL, annotation=str)},
    )

    signature, native, names = v101._build_signature(command)

    assert native is False
    assert names == ("arguments",)
    assert "arguments" in signature.parameters


def test_ai_timeout_has_safe_code_headroom():
    old = v101.ai_service.REQUEST_TIMEOUT_SECONDS
    try:
        v101.ai_service.REQUEST_TIMEOUT_SECONDS = 15.0
        v101._install_ai_timeout()
        assert v101.ai_service.REQUEST_TIMEOUT_SECONDS >= 75.0
    finally:
        v101.ai_service.REQUEST_TIMEOUT_SECONDS = old
