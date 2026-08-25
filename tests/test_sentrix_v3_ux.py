from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "cogs" / "sentrix_v3_ux.py"
RUNTIME = ROOT / "cogs" / "command_no_emoji_runtime.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_v3_module_compiles_and_has_no_discord_command_decorator() -> None:
    source = _source(MODULE)
    tree = ast.parse(source, filename=str(MODULE))
    forbidden = {"command", "hybrid_command", "group", "hybrid_group"}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(target, ast.Attribute):
                assert target.attr not in forbidden, (
                    "La fondation UX V3 ne doit jamais augmenter le registre de commandes."
                )


def test_v3_is_loaded_after_legacy_help_style_runtime() -> None:
    runtime = _source(RUNTIME)
    assert "install_sentrix_v3_ux" in runtime
    assert runtime.index("command_style_v2.install(bot)") < runtime.index("install_sentrix_v3_ux(bot)")


def test_v3_help_has_search_quick_actions_and_navigation() -> None:
    source = _source(MODULE)
    for marker in (
        "Centre de contrôle",
        "V3SearchModal",
        "V3HomeView",
        "V3PagesView",
        "V3Select",
        "Setup & logs",
        "Sécurité",
        "Modération",
        "Tickets",
        "Rechercher",
    ):
        assert marker in source


def test_v3_keeps_help_callback_instead_of_recreating_help_command() -> None:
    source = _source(MODULE)
    assert "help_command.callback = clean._clean_help_callback" in source
    assert "clean._help_home = _home_embed" in source
    assert "clean._category_pages = _category_pages" in source
    assert "clean._all_pages = _all_pages" in source
