from __future__ import annotations

import os
from unittest.mock import Mock

os.environ.setdefault("DISCORD_TOKEN", "x")

from discord import app_commands

from cogs import command_catalog_cleanup, slash_command_budget


def _command(name: str):
    item = Mock(spec=app_commands.Command)
    item.name = name
    return item


class _Tree:
    def __init__(self, roots):
        self.roots = list(roots)

    def get_commands(self, guild=None, type=None):
        return list(self.roots)

    def add_command(self, command, **kwargs):
        self.roots.append(command)
        return command

    def remove_command(self, name, **kwargs):
        for index, item in enumerate(self.roots):
            if str(getattr(item, "name", "")).casefold() == str(name).casefold():
                return self.roots.pop(index)
        return None


class _Bot:
    def __init__(self, tree):
        self.tree = tree
        self._sentrix_slash_budget_installed = False


def test_les_doublons_et_reglages_prefix_only_ne_consomme_pas_le_budget_slash():
    excluded = slash_command_budget._excluded_names()
    assert command_catalog_cleanup.PURE_DUPLICATE_COMMANDS <= excluded
    assert slash_command_budget.SLASH_PREFIX_ONLY <= excluded
    assert len(slash_command_budget._preferred_names()) <= slash_command_budget.GLOBAL_CHAT_INPUT_BUDGET


def test_une_commande_differee_est_retentee_quand_une_place_se_libere():
    roots = [_command(f"tmp-{index}") for index in range(100)]
    tree = _Tree(roots)
    bot = _Bot(tree)
    slash_command_budget.install(bot)

    late = _command("late-useful")
    assert tree.add_command(late) is None
    assert "late-useful" in bot._sentrix_skipped_global_slash
    assert any(item.name == "late-useful" for item in bot._sentrix_deferred_global_slash)

    tree.roots.pop()
    stats = slash_command_budget.finalize(bot)

    assert "late-useful" in stats["restored"]
    assert any(item.name == "late-useful" for item in tree.roots)
    assert len(tree.roots) <= 100
