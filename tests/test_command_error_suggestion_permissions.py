from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

from discord.ext import commands

from cogs import command_response_guard
import sentrix_product_update


def run(coro):
    return asyncio.run(coro)


def _texte_du_panneau(panneau) -> str:
    """Tout le texte affiché par un Panneau, composants compris."""
    morceaux: list[str] = []

    def parcourir(noeud):
        contenu = getattr(noeud, "content", None)
        if isinstance(contenu, str) and contenu.strip():
            morceaux.append(contenu)
        enfants = list(getattr(noeud, "children", []) or [])
        enfants += list(getattr(noeud, "items", []) or [])
        for enfant in enfants:
            parcourir(enfant)

    for enfant in getattr(panneau, "children", []) or []:
        parcourir(enfant)
    return "\n".join(morceaux)


def test_unknown_command_handler_uses_permission_filtered_suggestions(monkeypatch):
    """Le propriétaire final réutilise exactement le filtre de permissions partagé."""
    bot = object()
    ctx = SimpleNamespace(
        command=None,
        invoked_with="kik",
        clean_prefix="+",
        author=SimpleNamespace(id=123),
    )
    filtered = Mock(return_value=["kick"])

    monkeypatch.setattr(command_response_guard, "_typed_command_path", lambda *_args: "kik")
    monkeypatch.setattr(command_response_guard, "_command_suggestions", filtered)

    text = sentrix_product_update._unknown_command_text(bot, ctx)

    filtered.assert_called_once_with(bot, ctx, "kik")
    assert "+kick" in text
    assert "Vouliez-vous dire" in text
    assert "/aide" in text


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
