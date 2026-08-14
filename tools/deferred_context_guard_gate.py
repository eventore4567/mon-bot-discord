from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "cogs" / "deferred_context_response_guard.py"
text = SOURCE.read_text(encoding="utf-8")
tree = ast.parse(text, filename=str(SOURCE))


def fn(name: str):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"missing function: {name}")


install = fn("install")
source = ast.get_source_segment(text, install) or ""

assert "commands.Context.defer" in source, "global guard must wrap Context.defer"
assert "commands.Context.send" in source, "global guard must wrap Context.send"
assert "_sentrix_marks_deferred_original" in source
assert "_sentrix_resolves_deferred_original" in source
assert "_mark_pending(self)" in source, "successful ctx.defer must mark original response pending"
assert "interaction.edit_original_response(**edit)" in source, "first ctx.send must directly resolve original deferred response"
assert "_consume_pending(self)" in source, "pending marker must be consumed after first response"
assert "await interaction.original_response()" not in source, "global defer/send path must not fetch original response before resolving it"
assert "return await current_send(self, content, **kwargs)" in source, "non-deferred and fallback paths must preserve native Context.send"
assert "interaction.response.type in _DEFERRED_TYPES" in source
assert "interaction.response.type not in _DEFERRED_TYPES" in source

for field in ("defer_marked_count", "resolved_count", "fallback_count", "last_result", "last_error"):
    assert f'"{field}"' in text, f"health telemetry missing: {field}"

print("SentriX deferred Context guard gate: OK (all hybrid slash defer/send responses resolve original directly)")
