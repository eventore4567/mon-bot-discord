from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "cogs" / "slash_reliability_v7.py"
LOADER = ROOT / "cogs" / "__init__.py"
HEALTH = ROOT / "web" / "production_health.py"
text = SOURCE.read_text(encoding="utf-8")
loader_text = LOADER.read_text(encoding="utf-8")
health_text = HEALTH.read_text(encoding="utf-8")
tree = ast.parse(text, filename=str(SOURCE))


def function(name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Missing function: {name}")


def calls(node: ast.AST, attr: str) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Attribute) and func.attr == attr:
            return True
        if isinstance(func, ast.Name) and func.id == attr:
            return True
    return False


watchdog = function("_defer_watchdog")
settler = function("_settle_auto_deferred")
deferred_detector = function("_interaction_is_deferred")
installer = function("_install_auto_defer_completion_guard")
interaction_guard = function("_install_single_interaction_guard")
payload_check = function("_original_response_has_payload")

assert calls(watchdog, "defer"), "slash watchdog must still defer slow interactions"
assert calls(watchdog, "_mark_auto_deferred"), "watchdog defers should still be tracked after success"
assert "thinking=True" in ast.get_source_segment(text, watchdog), "watchdog must preserve thinking defer semantics"

watchdog_source = ast.get_source_segment(text, watchdog) or ""
assert watchdog_source.index("await interaction.response.defer(thinking=True)") < watchdog_source.index("_mark_auto_deferred(interaction)"), (
    "auto-defer must be marked only after Discord accepts the defer"
)

settler_source = ast.get_source_segment(text, settler) or ""
assert calls(settler, "_take_auto_deferred"), "watchdog tracker must still be consumed on completion"
assert calls(settler, "_interaction_is_deferred"), "completion must also detect command-owned defer responses"
assert calls(settler, "original_response"), "completion must inspect the original interaction response"
assert calls(settler, "_original_response_has_payload"), "existing command results must be preserved"
assert calls(settler, "edit_original_response"), "empty thinking placeholders must be resolved"
assert "Commande exécutée avec succès." in settler_source
assert "if not tracked_by_watchdog and not _interaction_is_deferred(interaction)" in settler_source, (
    "manual/command-owned defer responses must be eligible even when the watchdog never tracked them"
)
assert "last_completion_at" in settler_source, "live completion telemetry must be recorded"
assert "last_result" in settler_source, "live completion result must be observable"

manual_defer_source = ast.get_source_segment(text, deferred_detector) or ""
assert "deferred_channel_message" in manual_defer_source, "slash defer response type must be recognized"
assert "deferred_message_update" in manual_defer_source, "deferred update type must be recognized safely"

payload_source = ast.get_source_segment(text, payload_check) or ""
for field in ("content", "embeds", "attachments", "components", "stickers", "poll"):
    assert field in payload_source, f"payload detector must preserve existing {field}"

installer_source = ast.get_source_segment(text, installer) or ""
assert '"on_app_command_completion"' in installer_source, "native slash completion must be covered"
assert '"on_command_completion"' in installer_source, "hybrid slash completion must be covered"
assert "_sentrix_slash_auto_defer_completion_guard" in installer_source, "installer must be idempotent"

interaction_source = ast.get_source_segment(text, interaction_guard) or ""
assert "previous_check = tree.interaction_check" in interaction_source, "V7 must preserve the existing permission/blacklist tree check"
assert "previous_check(interaction)" in interaction_source, "V7 must delegate to the previous interaction check"
assert "inspect.isawaitable" in interaction_source, "previous async tree checks must be awaited"

install = function("install")
install_source = ast.get_source_segment(text, install) or ""
assert calls(install, "_install_auto_defer_completion_guard"), "completion guard must be installed"
assert "_sentrix_slash_reliability_v7_installed" in install_source, "runtime must expose an installed marker"

# Critical production wiring: previous patches passed CI but the module was never loaded by the bot.
assert "from .slash_reliability_v7 import install as install_slash_reliability_v7" in loader_text, (
    "slash reliability must be imported by the real cogs loader"
)
assert 'if _matches(name, "cogs.embed_builder")' in loader_text, "runtime must install after the final historical extension"
assert 'await _run_installer("fiabilité slash V7", install_slash_reliability_v7, bot)' in loader_text, (
    "slash reliability must be invoked by the production loader"
)

assert '"slash_reliability": _safe_slash_health(bot)' in health_text, "live /health must expose slash runtime state"
assert '"runtime_installed": bool(getattr(bot, "_sentrix_slash_reliability_v7_installed", False))' in health_text, (
    "health must prove the runtime is actually installed"
)

print("SentriX slash thinking cleanup gate: OK (runtime wired + watchdog + command-owned defer + live telemetry)")
