from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V79 = ROOT / "cogs" / "help_complete_v79.py"
V78 = ROOT / "cogs" / "help_components_v78.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_v79_catalog_includes_all_prefix_commands_without_hidden_filter():
    source = _source(V79)

    assert "for command in bot.walk_commands():" in source
    assert "command.hidden" in source  # documented intentionally, not used as a filter
    assert "if command.hidden" not in source
    assert "legacy._visible" not in source


def test_v79_catalog_includes_leaf_slash_commands_and_subcommands():
    source = _source(V79)

    assert "bot.tree.get_commands(type=discord.AppCommandType.chat_input)" in source
    assert "yield from walk(child, name)" in source
    assert "yield name, node" in source
    assert "entry.slash_name = slash_name" in source
    assert "entry.slash_command = slash_command" in source


def test_v79_merges_matching_prefix_and_slash_invocations():
    source = _source(V79)

    assert "key = _normalise(name)" in source
    assert "key = _normalise(slash_name)" in source
    assert "entry = entries.get(key)" in source


def test_v79_has_complete_catalog_button_and_paginated_listing():
    source = _source(V79)

    assert "LIST_PAGE_SIZE = 6" in source
    assert "Toutes les commandes" in source
    assert "self.show_all()" in source
    assert "self.rows = _catalog(self.bot)" in source


def test_v79_reports_prefix_slash_and_slash_only_counts():
    source = _source(V79)

    assert "prefix_count" in source
    assert "slash_count" in source
    assert "slash_only" in source


def test_v79_is_installed_by_v78_after_v78_patch():
    source = _source(V78)

    assert "help_complete_v79" in source
    assert "v79.install(bot)" in source
