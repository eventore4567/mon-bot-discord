#!/usr/bin/env python3
"""Audit du graphe d'execution Python de SentriX."""
from __future__ import annotations

import ast
import pathlib
from collections import deque

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME_DIRS = ("cogs", "database", "utils", "web")
ENTRY_FILES = ("main.py", "railway_boot.py", "railway_canary_boot.py")


def module_name(path: pathlib.Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def runtime_files() -> list[pathlib.Path]:
    result: list[pathlib.Path] = []
    for folder in RUNTIME_DIRS:
        base = ROOT / folder
        if base.exists():
            result.extend(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)
    for name in ("main.py", "config.py", "railway_boot.py", "railway_canary_boot.py"):
        path = ROOT / name
        if path.exists():
            result.append(path)
    return sorted(set(result))


FILES = runtime_files()
MODULE_TO_PATH: dict[str, pathlib.Path] = {}
PATH_TO_MODULE: dict[pathlib.Path, str] = {}
for path in FILES:
    mod = module_name(path)
    PATH_TO_MODULE[path] = mod
    if mod:
        MODULE_TO_PATH[mod] = path


def package_inits(mod: str) -> list[str]:
    parts = mod.split(".") if mod else []
    found: list[str] = []
    for i in range(1, len(parts)):
        pkg = ".".join(parts[:i])
        init = ROOT / pathlib.Path(*parts[:i]) / "__init__.py"
        if init.exists() and pkg in MODULE_TO_PATH:
            found.append(pkg)
    return found


def resolve_from(current: str, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    current_parts = current.split(".") if current else []
    current_path = MODULE_TO_PATH.get(current)
    if current_path is not None and current_path.name != "__init__.py":
        current_parts = current_parts[:-1]
    trim = max(0, node.level - 1)
    if trim:
        current_parts = current_parts[:-trim] if trim <= len(current_parts) else []
    if node.module:
        current_parts.extend(node.module.split("."))
    return ".".join(current_parts)


def add_if_local(targets: set[str], mod: str) -> None:
    if not mod:
        return
    if mod in MODULE_TO_PATH:
        targets.add(mod)
    for pkg in package_inits(mod):
        targets.add(pkg)


def dependencies(path: pathlib.Path) -> set[str]:
    current = PATH_TO_MODULE[path]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    targets: set[str] = set()

    for pkg in package_inits(current):
        add_if_local(targets, pkg)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add_if_local(targets, alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = resolve_from(current, node)
            add_if_local(targets, base)
            for alias in node.names:
                if alias.name == "*":
                    continue
                candidate = f"{base}.{alias.name}" if base else alias.name
                add_if_local(targets, candidate)
        elif isinstance(node, ast.Call):
            func = node.func
            call = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if call in {"import_module", "__import__", "load_extension"} and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    add_if_local(targets, first.value)

    # Couvre les listes explicites de modules telles que main.EXTENSIONS.
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in MODULE_TO_PATH:
            add_if_local(targets, node.value)

    targets.discard(current)
    return targets


def analyze() -> tuple[list[str], set[str], list[str]]:
    deps: dict[str, set[str]] = {}
    parse_errors: list[str] = []
    for path in FILES:
        mod = PATH_TO_MODULE[path]
        try:
            deps[mod] = dependencies(path)
        except Exception as exc:
            parse_errors.append(f"{path.relative_to(ROOT)}: {type(exc).__name__}: {exc}")
            deps[mod] = set()

    roots = {PATH_TO_MODULE[ROOT / name] for name in ENTRY_FILES if (ROOT / name) in PATH_TO_MODULE}
    reachable: set[str] = set()
    queue = deque(sorted(roots))
    while queue:
        mod = queue.popleft()
        if mod in reachable:
            continue
        reachable.add(mod)
        for dep in sorted(deps.get(mod, ())):
            if dep not in reachable:
                queue.append(dep)

    candidates = [
        path.relative_to(ROOT).as_posix()
        for path in FILES
        if PATH_TO_MODULE[path] not in reachable and path.relative_to(ROOT).as_posix() != "config.py"
    ]
    return candidates, reachable, parse_errors


def main() -> int:
    candidates, reachable, parse_errors = analyze()
    print(f"Runtime graph: {len(FILES)} fichiers Python analyses")
    print(f"Runtime graph: {len(reachable)} module(s) atteignable(s)")
    for item in parse_errors:
        print(f"[WARN] {item}")
    print(f"Runtime graph: {len(candidates)} candidat(s) non atteignable(s)")
    for item in candidates:
        print(f"ORPHAN_CANDIDATE {item}")
    for required in ("cogs", "web"):
        status = "REACHABLE" if required in reachable else "NOT_REACHABLE"
        print(f"PACKAGE_INIT {required}/__init__.py {status}")
    print("OK: audit de reachability termine; aucune suppression automatique")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
