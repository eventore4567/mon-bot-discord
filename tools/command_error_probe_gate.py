from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "cogs" / "command_error_probe.py"
PHASE = ROOT / "cogs" / "production_phase_runtime.py"
BOOT = ROOT / "railway_boot.py"
text = SOURCE.read_text(encoding="utf-8")
phase_text = PHASE.read_text(encoding="utf-8")
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

for field in ("hour_bucket", "command_name", "calls", "errors", "error_rate_pct", "avg_ms", "max_ms"):
    assert f'"{field}"' in safe_row

for forbidden_output in ('"guild_id":', '"user_id":', '"detail":', '"message":'):
    assert forbidden_output not in safe_row, f"safe metric leaks {forbidden_output}"
    assert forbidden_output not in health, f"health leaks {forbidden_output}"

assert "production_command_metrics" in refresh
assert "MAX(hour_bucket)" in refresh
assert "errors>0" in refresh
assert "command_name,calls,errors,total_ms,max_ms" in refresh

# The probe must match the authoritative ProductionPhase hourly schema exactly.
for column in ("hour_bucket", "command_name", "calls", "errors", "total_ms", "max_ms"):
    assert column in phase_text, f"ProductionPhase hourly schema missing {column}"
assert "command_kind" not in refresh
assert "duration_ms" not in refresh
assert "status='error'" not in refresh

assert '"cogs.command_error_probe" not in bot_main.EXTENSIONS' in boot_text
assert 'bot_main.EXTENSIONS.append("cogs.command_error_probe")' in boot_text

print("SentriX command error probe gate: OK (real ProductionPhase hourly schema, no PII)")
