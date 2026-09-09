from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import sentrix_v95_runtime as v95
import sentrix_v98_slash as v98


def _target(original: str, root: str, leaf: str | None = None) -> v95.SlashTarget:
    async def callback(ctx):
        return None

    command = commands.Command(
        callback,
        name=original.replace(" ", "-")[:32],
        description=f"Commande de test {original}",
    )
    return v95.SlashTarget(
        command=command,
        root_name=root,
        leaf_name=leaf or original.replace(" ", "-"),
        original_name=original,
        native_options=True,
    )


def test_ticket_panel_uses_semantic_path():
    target = _target("ticketpanel", "ticket", "panel")
    assert v98.semantic_bucket("ticket", target) == "panel"
    assert v98.semantic_leaf("ticket", "panel", target) == "create"

    toggle = _target("ticketpanel-toggle", "ticket", "panel-toggle")
    assert v98.semantic_bucket("ticket", toggle) == "panel"
    assert v98.semantic_leaf("ticket", "panel", toggle) == "toggle"


def test_security_automod_aliases_are_readable():
    target = _target("antiraid", "security")
    assert v98.semantic_bucket("security", target) == "automod"
    assert v98.semantic_leaf("security", "automod", target) == "raid"


def test_install_normalizes_main_category_roots(monkeypatch):
    monkeypatch.setattr(v95, "CATEGORY_ROOTS", dict(v95.CATEGORY_ROOTS))
    monkeypatch.setattr(v95, "GROUP_DESCRIPTIONS", dict(v95.GROUP_DESCRIPTIONS))
    monkeypatch.setattr(v95, "_add_grouped_surface", v95._add_grouped_surface)
    monkeypatch.delattr(v95, "_sentrix_v98_grouped_slash", raising=False)

    v98.install()

    assert v95.CATEGORY_ROOTS["levels"] == "level"
    assert v95.CATEGORY_ROOTS["games"] == "game"
    assert v95.CATEGORY_ROOTS["roles"] == "role"
    assert v95.CATEGORY_ROOTS["sanctions"] == "moderation"
    assert v95._add_grouped_surface is v98._add_grouped_surface_v98


def test_overflow_uses_semantic_groups_never_page_numbers(monkeypatch):
    bot = commands.Bot(command_prefix="+", intents=discord.Intents.none())
    targets = [
        _target(f"guard-{index}", "security")
        for index in range(30)
    ]
    monkeypatch.setattr(v95, "_build_targets", lambda _bot: targets)

    report = v98._add_grouped_surface_v98(bot)

    root = bot.tree.get_command("security")
    assert isinstance(root, app_commands.Group)
    assert root.commands
    assert all(isinstance(child, app_commands.Group) for child in root.commands)
    assert all("page-" not in child.name for child in root.commands)
    assert all(len(child.commands) <= v95.MAX_CHILDREN for child in root.commands)
    assert any(child.name == "general" for child in root.commands)
    assert all(" page-" not in path for path in report)
    assert len(report) == 30
