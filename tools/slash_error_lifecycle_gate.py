from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERROR_GUARD = ROOT / "cogs" / "slash_error_completion_guard.py"
CONFLICT_GUARD = ROOT / "cogs" / "legacy_observability_conflict_guard.py"
LEGACY = ROOT / "cogs" / "production_observability_v9.py"
PHASE = ROOT / "cogs" / "production_phase_runtime.py"
BOOT = ROOT / "railway_boot.py"
error_text = ERROR_GUARD.read_text(encoding="utf-8")
conflict_text = CONFLICT_GUARD.read_text(encoding="utf-8")
legacy_text = LEGACY.read_text(encoding="utf-8")
phase_text = PHASE.read_text(encoding="utf-8")
boot_text = BOOT.read_text(encoding="utf-8")
error_tree = ast.parse(error_text, filename=str(ERROR_GUARD))


def function(name: str):
    for node in ast.walk(error_tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Missing function: {name}")


def source(name: str) -> str:
    return ast.get_source_segment(error_text, function(name)) or ""

settle = source("_settle_error_defer")
install = source("install")

assert "interaction.response.is_done()" in settle
assert "_is_deferred(interaction)" in settle
assert "interaction.original_response()" in settle
assert "_has_payload(original)" in settle
assert "interaction.edit_original_response" in settle
assert "error_defer_settled" in settle
assert "La commande est terminée" in error_text

# The cleanup must execute even if an older CommandTree error handler crashes.
assert "finally:" in install
assert "await _settle_error_defer(bot, interaction, error)" in install
assert "bot.tree.on_error = error_with_defer_completion" in install
assert "_sentrix_original" in install

# Prove the schema collision really exists and is intentionally quarantined before V7.
assert "CREATE TABLE IF NOT EXISTS production_command_metrics" in legacy_text
assert "guild_id INTEGER" in legacy_text and "command_kind TEXT" in legacy_text
assert "CREATE TABLE IF NOT EXISTS production_command_metrics" in phase_text
assert "hour_bucket INTEGER" in phase_text and "calls INTEGER" in phase_text
assert "production_observability_v9.setup = disabled_legacy_observability" in conflict_text
assert 'runtime_bot.remove_cog("ProductionObservabilityV9")' in conflict_text

pre = boot_text.index('bot_main.EXTENSIONS.append("cogs.legacy_observability_conflict_guard")')
v7 = boot_text.index('bot_main.EXTENSIONS.append("cogs.slash_reliability_v7")')
post = boot_text.index('bot_main.EXTENSIONS.append("cogs.slash_error_completion_guard")')
assert pre < v7 < post, "conflict guard must precede V7 and error completion guard must be last"
assert post > boot_text.index('bot_main.EXTENSIONS.append("cogs.setup_auto_fix")')

print("SentriX slash error lifecycle gate: OK (schema collision quarantined, defer closed on success or error)")
