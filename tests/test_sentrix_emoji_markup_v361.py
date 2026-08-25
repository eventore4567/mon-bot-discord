from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "cogs" / "sentrix_emoji_markup_guard_v361.py"
RUNTIME = ROOT / "cogs" / "command_no_emoji_runtime.py"


def test_guard_adds_no_discord_command():
    tree = ast.parse(GUARD.read_text(encoding="utf-8"))
    forbidden = {"command", "hybrid_command", "group", "hybrid_group"}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                decorator = decorator.func
            if isinstance(decorator, ast.Attribute):
                assert decorator.attr not in forbidden


def test_broken_v36_markup_pattern_is_repaired():
    source = GUARD.read_text(encoding="utf-8")
    assert "_BROKEN_V36_RE" in source
    pattern = re.compile(r"(?<!<)(?:a:|:)?sxv36_[A-Za-z0-9_~]+:\d+>")
    assert pattern.sub("", "a:sxv36_update:1541658913592713327> Configuration").strip() == "Configuration"
    valid = "<a:sxv36_update:1541658913592713327> Configuration"
    assert pattern.sub("", valid) == valid


def test_guard_preserves_full_custom_emoji_token():
    source = GUARD.read_text(encoding="utf-8")
    assert "_CUSTOM_PREFIX_RE" in source
    assert 'return premium_style.clip(f"{token} {cleaned}", 256)' in source


def test_guard_installs_after_existing_v3_renderers():
    source = RUNTIME.read_text(encoding="utf-8")
    help_pos = source.index("install_help_cooldown_exemption_v3(bot)")
    error_pos = source.index("install_error_experience_v3(bot)")
    guard_pos = source.index("install_emoji_markup_guard_v361(bot)")
    assert help_pos < error_pos < guard_pos
