#!/usr/bin/env python3
"""Audit statique rapide du code actif SentriX.

Vérifie les erreurs qui peuvent casser un déploiement avant même de lancer Discord :
syntaxe Python, extensions manquantes, imports relatifs cassés dans cogs/__init__.py,
limites de texte Discord connues et appels bloquants time.sleep() dans une coroutine.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("cogs", "database", "utils", "web", "tools")
ROOT_FILES = ("main.py", "config.py")

errors: list[str] = []
warnings: list[str] = []
checked = 0


def source_files() -> list[pathlib.Path]:
    files = [ROOT / name for name in ROOT_FILES]
    for folder in SOURCE_DIRS:
        base = ROOT / folder
        if base.exists():
            files.extend(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)
    return sorted(set(files))


def literal_str(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def call_name(node: ast.Call) -> str:
    parts: list[str] = []
    cur: ast.AST | None = node.func
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def check_decorator_limits(path: pathlib.Path, tree: ast.AST) -> None:
    command_suffixes = (
        "commands.command", "commands.hybrid_command", "commands.group",
        "commands.hybrid_group", "app_commands.command",
    )
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            name = call_name(dec)
            if any(name.endswith(suffix) for suffix in command_suffixes):
                for kw in dec.keywords:
                    if kw.arg == "description":
                        value = literal_str(kw.value)
                        if value is not None and len(value) > 100:
                            errors.append(
                                f"{path.relative_to(ROOT)}:{node.lineno}: description Discord >100 caractères ({len(value)})"
                            )
            if name.endswith("app_commands.describe"):
                for kw in dec.keywords:
                    value = literal_str(kw.value)
                    if value is not None and len(value) > 100:
                        errors.append(
                            f"{path.relative_to(ROOT)}:{node.lineno}: description de paramètre '{kw.arg}' >100 caractères ({len(value)})"
                        )


def check_async_blocking_sleep(path: pathlib.Path, tree: ast.AST) -> None:
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            if call_name(node) == "time.sleep":
                errors.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}: time.sleep() bloque la boucle asyncio dans '{fn.name}'"
                )


def parse_main_extensions() -> None:
    main_path = ROOT / "main.py"
    tree = ast.parse(main_path.read_text(encoding="utf-8"), filename=str(main_path))
    extensions: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "EXTENSIONS" for t in node.targets):
            if isinstance(node.value, (ast.List, ast.Tuple)):
                extensions = [v.value for v in node.value.elts if isinstance(v, ast.Constant) and isinstance(v.value, str)]
            break
    if not extensions:
        errors.append("main.py: impossible de lire EXTENSIONS")
        return
    for module in extensions:
        candidate = ROOT / (module.replace(".", "/") + ".py")
        package = ROOT / module.replace(".", "/") / "__init__.py"
        if not candidate.exists() and not package.exists():
            errors.append(f"main.py: extension introuvable: {module}")


def check_cogs_relative_imports() -> None:
    init_path = ROOT / "cogs" / "__init__.py"
    tree = ast.parse(init_path.read_text(encoding="utf-8"), filename=str(init_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            candidate = ROOT / "cogs" / (node.module.replace(".", "/") + ".py")
            package = ROOT / "cogs" / node.module.replace(".", "/") / "__init__.py"
            if not candidate.exists() and not package.exists():
                errors.append(f"cogs/__init__.py:{node.lineno}: import relatif introuvable: .{node.module}")


def check_obvious_conflict_markers(path: pathlib.Path, text: str) -> None:
    for marker in ("<<<<<<< ", "=======\n", ">>>>>>> "):
        if marker in text:
            errors.append(f"{path.relative_to(ROOT)}: marqueur de conflit Git détecté ({marker.strip()})")
            return


def main() -> int:
    global checked
    for path in source_files():
        if not path.exists():
            errors.append(f"fichier requis manquant: {path.relative_to(ROOT)}")
            continue
        text = path.read_text(encoding="utf-8")
        check_obvious_conflict_markers(path, text)
        try:
            tree = ast.parse(text, filename=str(path))
            compile(tree, str(path), "exec")
        except (SyntaxError, ValueError) as exc:
            errors.append(f"{path.relative_to(ROOT)}: syntaxe invalide: {exc}")
            continue
        checked += 1
        check_decorator_limits(path, tree)
        check_async_blocking_sleep(path, tree)

    try:
        parse_main_extensions()
        check_cogs_relative_imports()
    except Exception as exc:
        errors.append(f"audit structurel impossible: {type(exc).__name__}: {exc}")

    print(f"SentriX audit: {checked} fichier(s) Python vérifié(s)")
    for warning in warnings:
        print(f"[WARN] {warning}")
    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"ECHEC: {len(errors)} problème(s) bloquant(s)")
        return 1
    print("OK: aucun problème statique bloquant détecté")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
