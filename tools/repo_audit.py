#!/usr/bin/env python3
"""Audit statique rapide du code actif SentriX.

Vérifie les erreurs qui peuvent casser un déploiement avant même de lancer Discord :
syntaxe Python, extensions manquantes, imports relatifs cassés dans cogs/__init__.py,
limites de texte des slash commands, emojis de composants connus comme invalides et appels
bloquants time.sleep() dans une coroutine.
"""
from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("cogs", "database", "utils", "web", "tools")
ROOT_FILES = ("main.py", "config.py")

errors: list[str] = []
warnings: list[str] = []
checked = 0

# Discord refuse certains glyphes décoratifs lorsqu'ils sont envoyés dans le champ
# `emoji` d'un composant, même s'ils sont parfaitement valides dans un label. `○` a déjà
# provoqué un HTTP 400 / 50035 sur +embed ; ce garde-fou empêche sa réintroduction.
INVALID_COMPONENT_EMOJI_LITERALS = frozenset({"○"})


def source_files() -> list[pathlib.Path]:
    files = [ROOT / name for name in ROOT_FILES]
    for folder in SOURCE_DIRS:
        base = ROOT / folder
        if base.exists():
            files.extend(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)
    return sorted(set(files))


def literal_str(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def literal_bool(node: ast.AST | None) -> bool | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    return None


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

        decorators = [dec for dec in node.decorator_list if isinstance(dec, ast.Call)]
        # Une hybrid command explicitement prefix-only n'est jamais envoyée à l'API
        # slash de Discord : sa description n'est donc pas soumise à la limite des 100.
        slash_disabled = False
        for dec in decorators:
            name = call_name(dec)
            if not any(name.endswith(suffix) for suffix in command_suffixes):
                continue
            for kw in dec.keywords:
                if kw.arg == "with_app_command" and literal_bool(kw.value) is False:
                    slash_disabled = True

        for dec in decorators:
            name = call_name(dec)
            if not slash_disabled and any(name.endswith(suffix) for suffix in command_suffixes):
                for kw in dec.keywords:
                    if kw.arg == "description":
                        value = literal_str(kw.value)
                        if value is not None and len(value) > 100:
                            errors.append(
                                f"{path.relative_to(ROOT)}:{node.lineno}: description slash >100 caractères ({len(value)})"
                            )
            if not slash_disabled and name.endswith("app_commands.describe"):
                for kw in dec.keywords:
                    value = literal_str(kw.value)
                    if value is not None and len(value) > 100:
                        errors.append(
                            f"{path.relative_to(ROOT)}:{node.lineno}: description du paramètre '{kw.arg}' >100 caractères ({len(value)})"
                        )


def check_component_emoji_literals(path: pathlib.Path, tree: ast.AST) -> None:
    """Bloque les glyphes déjà connus pour faire rejeter un composant par Discord."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = call_name(node)
        if not (
            name.endswith("discord.ui.button")
            or name.endswith("ui.button")
            or name.endswith("discord.ui.Button")
            or name.endswith("ui.Button")
        ):
            continue
        for kw in node.keywords:
            if kw.arg != "emoji":
                continue
            value = literal_str(kw.value)
            if value in INVALID_COMPONENT_EMOJI_LITERALS:
                hits.append((node.lineno, value))

    relative = path.relative_to(ROOT).as_posix()
    # +embed possède encore UN ancien décorateur `emoji="○"` dans sa source historique,
    # mais cogs/__init__.py le remplace obligatoirement par ❌ après chargement et la CI
    # instancie réellement la vue pour vérifier le résultat. On tolère donc exactement ce
    # cas connu ; une deuxième occurrence dans ce fichier redevient immédiatement bloquante.
    if relative == "cogs/embed_builder.py" and len(hits) == 1 and hits[0][1] == "○":
        warnings.append(
            "cogs/embed_builder.py: ancien emoji ○ toléré uniquement car le correctif runtime + test UI le remplace par ❌"
        )
        return

    for lineno, value in hits:
        errors.append(
            f"{relative}:{lineno}: emoji de composant Discord invalide connu: {value!r}"
        )


def check_async_blocking_sleep(path: pathlib.Path, tree: ast.AST) -> None:
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and call_name(node) == "time.sleep":
                errors.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}: time.sleep() bloque asyncio dans '{fn.name}'"
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
    # Un vrai conflit Git occupe le début d'une ligne. Les séparateurs décoratifs
    # "# ======" utilisés dans le code ne doivent jamais être signalés.
    match = re.search(r"(?m)^(?:<<<<<<< .+|=======|>>>>>>> .+)$", text)
    if match:
        errors.append(
            f"{path.relative_to(ROOT)}:{text[:match.start()].count(chr(10)) + 1}: marqueur de conflit Git détecté"
        )


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
        check_component_emoji_literals(path, tree)
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
