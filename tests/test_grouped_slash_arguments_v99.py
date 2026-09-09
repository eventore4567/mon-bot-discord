from __future__ import annotations

import asyncio

import discord
from discord.ext import commands

import sentrix_grouped_slash_fix as fix
import sentrix_v95_runtime as v95


def test_keyword_only_text_is_forwarded_as_keyword_argument():
    async def callback(ctx, langue: str, *, texte: str):
        return None

    command = commands.Command(callback, name="ai-translate")
    _signature, native, option_names = v95._build_signature(command)

    assert native is True
    assert fix._supports_direct_binding(command, option_names) is True

    ctx = object()
    args, kwargs = asyncio.run(
        fix._bind_native_arguments(
            command,
            ctx,
            option_names,
            {"langue": "anglais", "texte": "bonjour tout le monde"},
        )
    )

    assert args == [ctx, "anglais"]
    assert kwargs == {"texte": "bonjour tout le monde"}


def test_ai_question_keeps_spaces_without_stringview_reparse():
    async def callback(ctx, *, question: str):
        return None

    command = commands.Command(callback, name="ai")
    _signature, native, option_names = v95._build_signature(command)
    question = "explique moi ce texte sans perdre les espaces"

    assert native is True
    args, kwargs = asyncio.run(
        fix._bind_native_arguments(command, object(), option_names, {"question": question})
    )

    assert len(args) == 1
    assert kwargs["question"] == question


def test_native_discord_object_is_not_serialized_back_to_text():
    async def callback(ctx, *, fichier: discord.Attachment):
        return None

    command = commands.Command(callback, name="upload")
    _signature, native, option_names = v95._build_signature(command)
    attachment_marker = object()

    assert native is True
    _args, kwargs = asyncio.run(
        fix._bind_native_arguments(
            command,
            object(),
            option_names,
            {"fichier": attachment_marker},
        )
    )

    assert kwargs["fichier"] is attachment_marker


def test_optional_gap_uses_original_default_instead_of_rejecting_next_option():
    async def callback(ctx, premier: str | None = None, second: str = "défaut"):
        return None

    command = commands.Command(callback, name="optional-gap")
    _signature, native, option_names = v95._build_signature(command)

    assert native is True
    args, kwargs = asyncio.run(
        fix._bind_native_arguments(
            command,
            object(),
            option_names,
            {"premier": None, "second": "fourni"},
        )
    )

    assert args[1:] == [None, "fourni"]
    assert kwargs == {}


def test_prefix_subcommand_with_early_parent_callback_keeps_legacy_path():
    async def root_callback(ctx):
        return None

    async def child_callback(ctx, *, texte: str):
        return None

    root = commands.Group(root_callback, name="root", invoke_without_command=False)
    child = commands.Command(child_callback, name="child")
    root.add_command(child)
    _signature, native, option_names = v95._build_signature(child)

    assert native is True
    assert fix._supports_direct_binding(child, option_names) is False


def test_compact_errors_are_plain_sentences():
    cooldown = commands.CommandOnCooldown(
        commands.Cooldown(1, 10.0),
        3.2,
        commands.BucketType.user,
    )

    assert fix._short_error(cooldown) == "Cette commande est en cooldown. Réessaie dans 3 s."
    assert "embed" not in fix._short_error(commands.BadArgument("bad")).casefold()
