from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "cogs" / "slash_reliability_v7.py"
text = SOURCE.read_text(encoding="utf-8")
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
installer = function("_install_auto_defer_completion_guard")
payload_check = function("_original_response_has_payload")

assert calls(watchdog, "defer"), "slash watchdog must still defer slow interactions"
assert calls(watchdog, "_mark_auto_deferred"), "auto-defer must be tracked only after it succeeds"
assert "thinking=True" in ast.get_source_segment(text, watchdog), "watchdog must preserve thinking defer semantics"

watchdog_source = ast.get_source_segment(text, watchdog) or ""
assert watchdog_source.index("await interaction.response.defer(thinking=True)") < watchdog_source.index("_mark_auto_deferred(interaction)"), (
    "auto-defer must be marked only after Discord accepts the defer"
)

assert calls(settler, "_take_auto_deferred"), "completion must affect only SentriX auto-deferred interactions"
assert calls(settler, "original_response"), "completion must inspect the original interaction response"
assert calls(settler, "_original_response_has_payload"), "existing command results must be preserved"
assert calls(settler, "edit_original_response"), "empty thinking placeholders must be resolved"
assert "Commande exécutée avec succès." in (ast.get_source_segment(text, settler) or "")

payload_source = ast.get_source_segment(text, payload_check) or ""
for field in ("content", "embeds", "attachments", "components", "stickers", "poll"):
    assert field in payload_source, f"payload detector must preserve existing {field}"

installer_source = ast.get_source_segment(text, installer) or ""
assert '"on_app_command_completion"' in installer_source, "native slash completion must be covered"
assert '"on_command_completion"' in installer_source, "hybrid slash completion must be covered"
assert "_sentrix_slash_auto_defer_completion_guard" in installer_source, "installer must be idempotent"

install = function("install")
assert calls(install, "_install_auto_defer_completion_guard"), "completion guard must be installed in production"

print("SentriX slash thinking cleanup gate: OK")
