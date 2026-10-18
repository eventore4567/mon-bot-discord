"""Régression : discord.ext.commands.Greedy ne doit pas casser la surface slash."""
from __future__ import annotations

import inspect

import discord
from discord.ext import commands

import sentrix_v95_runtime as v95


def test_greedy_annotation_uses_text_fallback_without_typeerror():
    annotation = commands.Greedy[discord.Role]
    assert v95._native_annotation(annotation) is str


def test_greedy_callback_can_build_a_slash_signature():
    async def callback(ctx, roles: commands.Greedy[discord.Role]):
        return None

    command = commands.Command(callback, name="roles")
    signature, native, option_names = v95._build_signature(command)

    assert isinstance(signature, inspect.Signature)
    assert option_names == ("roles",)
    assert not native
    assert signature.parameters["roles"].annotation is str


def test_supported_native_discord_types_still_work():
    for annotation in (str, int, float, bool, discord.Role, discord.Member, discord.User):
        assert v95._native_annotation(annotation) is annotation
