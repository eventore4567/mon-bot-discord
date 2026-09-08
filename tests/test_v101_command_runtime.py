from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
from discord.ext import commands

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


def test_opaque_setup_wrapper_with_polluted_clean_params_exposes_nothing():
    async def wrapper(*args, **kwargs):
        return None

    command = SimpleNamespace(
        callback=wrapper,
        cog=None,
        qualified_name="setup",
        clean_params={
            "ctx": _parameter("ctx"),
            "args": _parameter("args", inspect.Parameter.VAR_POSITIONAL),
            "kwargs": _parameter("kwargs", inspect.Parameter.VAR_KEYWORD),
        },
    )

    assert v101._is_opaque_runtime_wrapper(command) is True
    signature, native, names = v101._build_signature(command)

    assert native is True
    assert names == ()
    assert tuple(signature.parameters) == ("interaction",)


def test_real_ctx_args_varargs_still_use_legacy_arguments_option():
    async def legacy(ctx, *args: str):
        return None

    command = SimpleNamespace(
        callback=legacy,
        cog=None,
        qualified_name="legacy",
        clean_params={"args": _parameter("args", inspect.Parameter.VAR_POSITIONAL, annotation=str)},
    )

    assert v101._is_opaque_runtime_wrapper(command) is False
    signature, native, names = v101._build_signature(command)

    assert native is False
    assert names == ("arguments",)
    assert "arguments" in signature.parameters


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


@pytest.mark.asyncio
async def test_ambiguous_detached_cog_fails_closed_instead_of_picking_first():
    first = _EmbedBuilder()
    second = _EmbedBuilder()
    bot = SimpleNamespace(cogs={"EmbedBuilderOne": first, "EmbedBuilderTwo": second})
    ctx = SimpleNamespace(bot=bot)
    command = SimpleNamespace(
        callback=_EmbedBuilder.embedconfig_addrole,
        cog=None,
        qualified_name="embedconfig addrole",
        clean_params={"role": _parameter("role", annotation=str)},
    )

    with pytest.raises(commands.CommandError, match="ambigu"):
        await v101._bind_native_arguments(
            command,
            ctx,
            ("role",),
            {"role": "staff"},
        )


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


def test_trace_summary_contains_types_but_never_values():
    marker = "THIS_MUST_NOT_APPEAR"
    summary = v101._option_type_summary({"question": marker, "count": 3, "enabled": True})

    assert summary == {"question": "str", "count": "int", "enabled": "bool"}
    assert marker not in repr(summary)


def test_ai_timeout_has_safe_code_headroom():
    old = v101.ai_service.REQUEST_TIMEOUT_SECONDS
    try:
        v101.ai_service.REQUEST_TIMEOUT_SECONDS = 15.0
        v101._install_ai_timeout()
        assert v101.ai_service.REQUEST_TIMEOUT_SECONDS >= 75.0
    finally:
        v101.ai_service.REQUEST_TIMEOUT_SECONDS = old
