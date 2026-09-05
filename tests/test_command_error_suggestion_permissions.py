from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

from discord.ext import commands

from cogs import command_response_guard, error_experience_v3


def run(coro):
    return asyncio.run(coro)


def test_unknown_command_handler_uses_permission_filtered_suggestions(monkeypatch):
    bot = object()
    ctx = SimpleNamespace(
        command=None,
        invoked_with="kik",
        clean_prefix="+",
        author=SimpleNamespace(id=123),
    )
    filtered = Mock(return_value=["kick"])
    sender = AsyncMock()

    monkeypatch.setattr(error_experience_v3, "_can_reply_unknown", lambda *_args: True)
    monkeypatch.setattr(error_experience_v3, "_command_suggestions", filtered)
    monkeypatch.setattr(error_experience_v3, "_send_plain", sender)

    handled = run(
        error_experience_v3._handle_user_error(
            bot,
            ctx,
            commands.CommandNotFound("kik"),
        )
    )

    assert handled is True
    filtered.assert_called_once_with(bot, ctx, "kik")
    sender.assert_awaited_once_with(ctx, "Commande introuvable. Essayez `+kick`.")


def test_command_suggestions_hide_commands_without_required_permission(monkeypatch):
    fake_main = ModuleType("main")
    fake_main.PUBLIC_COMMANDS = {"help"}
    fake_main.OWNER_ONLY_COMMANDS = {"eval"}
    fake_main.DISCORD_PERMISSION_COMMANDS = {"kick": "kick_members"}
    fake_main.CATEGORY_COMMANDS = {}
    monkeypatch.setitem(sys.modules, "main", fake_main)

    def command(name: str):
        return SimpleNamespace(
            name=name,
            qualified_name=name,
            aliases=(),
            parent=None,
            root_parent=None,
            hidden=False,
            enabled=True,
        )

    bot = SimpleNamespace(walk_commands=lambda: [command("help"), command("kick"), command("eval")])

    no_staff_perms = SimpleNamespace(
        administrator=False,
        manage_guild=False,
        kick_members=False,
    )
    ctx = SimpleNamespace(author=SimpleNamespace(guild_permissions=no_staff_perms))
    assert "kick" not in command_response_guard._command_suggestions(bot, ctx, "kik")
    assert "eval" not in command_response_guard._command_suggestions(bot, ctx, "evl")

    kick_perms = SimpleNamespace(
        administrator=False,
        manage_guild=False,
        kick_members=True,
    )
    ctx = SimpleNamespace(author=SimpleNamespace(guild_permissions=kick_perms))
    assert command_response_guard._command_suggestions(bot, ctx, "kik") == ["kick"]
