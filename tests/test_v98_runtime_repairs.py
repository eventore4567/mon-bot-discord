from __future__ import annotations

import inspect
from collections import OrderedDict

import discord
from discord.ext import commands

import sentrix_v98_runtime as v98


class _Param:
    def __init__(self, annotation, *, required=False, kind=inspect.Parameter.POSITIONAL_OR_KEYWORD):
        self.annotation = annotation
        self.required = required
        self.kind = kind
        self.default = inspect.Parameter.empty if required else None


class _Command:
    def __init__(self, name, params):
        self.name = name
        self.qualified_name = name
        self.clean_params = OrderedDict(params)


def test_fallback_signature_keeps_native_attachment():
    command = _Command(
        "proof-upload",
        [
            ("title", _Param(str, required=False)),
            ("description", _Param(str, required=False)),
            ("file", _Param(discord.Attachment, required=True)),
        ],
    )

    signature, native, option_names = v98._build_signature(command)

    assert native is False
    assert option_names[0] == "arguments"
    assert "file" in option_names
    assert signature.parameters["file"].annotation is discord.Attachment
    assert signature.parameters["file"].default is inspect.Parameter.empty


def test_greedy_annotation_falls_back_to_text_without_hash_crash():
    annotation = commands.Greedy[discord.Member]
    assert v98._native_annotation(annotation) is str


def test_ai_legacy_command_is_exposed_as_ask():
    command = _Command("ai", [])
    assert v98._group_for(command) == ("ai", "ask")


def test_ai_translate_is_exposed_under_ai_group():
    command = _Command("ai-translate", [])
    assert v98._group_for(command) == ("ai", "translate")


def test_bridge_uses_bot_invoke_not_direct_root_invoke():
    source = inspect.getsource(v98._invoke_original)
    assert "await bot.invoke(ctx)" in source
    assert "await root.invoke(ctx)" not in source


def test_ticket_repair_is_conservative_on_discord_errors():
    source = inspect.getsource(v98._patch_ticket_runtime)
    assert "discord.NotFound" in source
    assert "discord.Forbidden, discord.HTTPException" in source
    assert "status='ferme'" in source
    assert "on_guild_channel_delete" in source


def test_setup_permission_patch_accepts_manage_guild():
    source = inspect.getsource(v98._patch_setup_permissions)
    assert "member.guild_permissions.manage_guild" in source
    assert "Gérer le serveur" in source


def test_ai_group_contains_expected_runtime_controls():
    source = inspect.getsource(v98._install_ai_controls)
    for name in ("enable", "disable", "reset", "memory", "model", "help", "search"):
        assert f'add("{name}"' in source
