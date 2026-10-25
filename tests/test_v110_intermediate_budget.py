"""La réaffirmation slash V110 doit respecter le budget global Discord."""
from __future__ import annotations

from types import SimpleNamespace

import sentrix_command_surface_v110 as v110
from cogs import slash_command_budget


class FakeTree:
    def __init__(self, names):
        self.items = [SimpleNamespace(name=name) for name in names]

    def get_commands(self, *, guild=None, type=None):
        return list(self.items)

    def remove_command(self, name, *, type=None):
        removed = next((cmd for cmd in self.items if cmd.name == name), None)
        self.items = [cmd for cmd in self.items if cmd.name != name]
        return removed


def test_v110_reassert_respects_100_roots_and_keeps_priority(monkeypatch):
    # 101 racines intermédiaires, comme dans l'audit réel. Le catalogue
    # public les remplace ensuite, mais l'arbre transitoire doit être valide.
    names = [f"legacy-{i}" for i in range(99)] + ["help", "setup"]
    bot = SimpleNamespace(tree=FakeTree(names))

    monkeypatch.setattr(v110, "STANDARD_DIRECT_SLASH", {})
    monkeypatch.setattr(v110, "STANDARD_GROUPED_SLASH", {})
    monkeypatch.setattr(slash_command_budget, "_required_names", lambda: {"help", "setup"})
    monkeypatch.setattr(slash_command_budget, "_preferred_names", lambda: {"help", "setup"})
    monkeypatch.setattr(slash_command_budget, "_excluded_names", lambda: set())

    installed, missing = v110.reassert_standard_slash_surface(bot)
    assert installed == 0
    assert missing == []
    assert len(bot.tree.items) == 100
    assert {"help", "setup"} <= {cmd.name for cmd in bot.tree.items}

    # Une seconde réaffirmation ne réintroduit pas la racine écartée.
    v110.reassert_standard_slash_surface(bot)
    assert len(bot.tree.items) == 100
