from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COGS = ROOT / "cogs"
GUARD = ROOT / "cogs" / "deferred_context_response_guard.py"
BOOT = ROOT / "railway_boot.py"
guard_text = GUARD.read_text(encoding="utf-8")
boot_text = BOOT.read_text(encoding="utf-8")


def dotted_name(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def decorator_names(node: ast.AsyncFunctionDef) -> set[str]:
    return {dotted_name(item.func if isinstance(item, ast.Call) else item) for item in node.decorator_list}


def call_names(node: ast.AsyncFunctionDef) -> list[str]:
    result: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            result.append(dotted_name(child.func))
    return result


legacy_patterns: list[tuple[str, int, str]] = []
for path in sorted(COGS.rglob("*.py")):
    if "__pycache__" in path.parts:
        continue
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except Exception:
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        decorators = decorator_names(node)
        if not any("command" in name for name in decorators):
            continue
        calls = call_names(node)
        if "ctx.defer" in calls and "ctx.send" in calls:
            legacy_patterns.append((str(path.relative_to(ROOT)), node.lineno, node.name))

# Global protection must be present and wired on the real Railway bootstrap. These
# assertions turn every legacy/future ctx.defer()+ctx.send() handler into a protected case.
assert "commands.Context.send = send_resolving_deferred_original" in guard_text
assert "interaction.response.type not in _DEFERRED_TYPES" in guard_text
assert "interaction.original_response()" in guard_text
assert "_has_payload(original)" in guard_text
assert "interaction.edit_original_response(**edit)" in guard_text
assert "return await current(self, content, **kwargs)" in guard_text, "native follow-up fallback must remain"
assert "attachments" in guard_text and "file" in guard_text and "files" in guard_text, "deferred file responses must be supported"
assert '"cogs.deferred_context_response_guard" not in bot_main.EXTENSIONS' in boot_text
assert 'bot_main.EXTENSIONS.append("cogs.deferred_context_response_guard")' in boot_text

# Error cleanup stays the final layer; Context.send resolver must be installed before it.
resolver_index = boot_text.index('bot_main.EXTENSIONS.append("cogs.deferred_context_response_guard")')
error_index = boot_text.index('bot_main.EXTENSIONS.append("cogs.slash_error_completion_guard")')
assert resolver_index < error_index

print(
    "SentriX defer/send audit: OK "
    f"({len(legacy_patterns)} deferred hybrid handler(s) protected globally; 0 unprotected)"
)
for path, line, name in legacy_patterns:
    print(f"PROTECTED {path}:{line} {name}")
