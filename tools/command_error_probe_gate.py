from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "cogs" / "command_error_probe.py"
BOOT = ROOT / "railway_boot.py"
text = SOURCE.read_text(encoding="utf-8")
boot_text = BOOT.read_text(encoding="utf-8")
tree = ast.parse(text, filename=str(SOURCE))


def function(name: str):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Missing function: {name}")


def source(name: str) -> str:
    return ast.get_source_segment(text, function(name)) or ""

safe_row = source("_safe_row")
refresh = source("_refresh")
health = source("_safe_health")

for field in ("command_name", "command_kind", "duration_ms", "status", "error_type", "created_at"):
    assert field in safe_row
for forbidden in ('"guild_id"', '"user_id"', '"detail"'):
    assert forbidden not in safe_row, f"safe metric leaks {forbidden}"
    assert forbidden not in health, f"health leaks {forbidden}"

assert "production_command_metrics" in refresh
assert "WHERE status='error'" in refresh
assert "ORDER BY id DESC LIMIT 1" in refresh
assert '"cogs.command_error_probe" not in bot_main.EXTENSIONS' in boot_text
assert 'bot_main.EXTENSIONS.append("cogs.command_error_probe")' in boot_text

print("SentriX command error probe gate: OK (latest command/error visible without PII or raw detail)")
