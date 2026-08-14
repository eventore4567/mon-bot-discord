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
    assert f'"{field}"' in safe_row

# Raw DB detail may be read only to derive the exception class, but must never be emitted.
for forbidden_output in ('"guild_id":', '"user_id":', '"detail":'):
    assert forbidden_output not in safe_row, f"safe metric leaks {forbidden_output}"
    assert forbidden_output not in health, f"health leaks {forbidden_output}"
assert '_error_type(row["detail"])' in safe_row, "raw detail may only feed the exception-class sanitizer"

assert "production_command_metrics" in refresh
assert "WHERE status='error'" in refresh
assert "ORDER BY id DESC LIMIT 1" in refresh
assert '"cogs.command_error_probe" not in bot_main.EXTENSIONS' in boot_text
assert 'bot_main.EXTENSIONS.append("cogs.command_error_probe")' in boot_text

print("SentriX command error probe gate: OK (latest command/error visible without PII or raw detail)")
