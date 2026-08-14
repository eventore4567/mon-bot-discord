from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COGS = ROOT / "cogs"


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


offenders: list[tuple[str, int, str, list[str]]] = []
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
        has_context_defer = "ctx.defer" in calls
        has_context_send = "ctx.send" in calls
        if has_context_defer and has_context_send:
            offenders.append((str(path.relative_to(ROOT)), node.lineno, node.name, calls))

if offenders:
    print("DEFER_SEND_ANTIPATTERN_FOUND")
    for path, line, name, calls in offenders:
        print(f"{path}:{line} {name} -> ctx.defer + ctx.send")
    raise SystemExit(1)

print("SentriX defer/send audit: OK (no hybrid command leaves a deferred original response for a followup)")
