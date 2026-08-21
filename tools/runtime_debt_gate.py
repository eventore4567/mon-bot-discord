#!/usr/bin/env python3
"""Empêche la dette runtime SentriX de repartir à la hausse.

Le dépôt contient encore plusieurs couches historiques qui seront consolidées par étapes.
Ce gate bloque déjà les régressions faciles à éviter : fichiers Python compilés suivis par
Git, retour d'un patch supprimé, et ajout accidentel de commandes publiques dans les
couches de qualité/observabilité qui doivent rester transversales.
"""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
NO_COMMAND_MODULES = (
    ROOT / "cogs" / "integrity_hardening.py",
    ROOT / "cogs" / "runtime_quality_v25.py",
    ROOT / "cogs" / "runtime_observability_v26.py",
    ROOT / "cogs" / "user_facing_hygiene.py",
)


def _tracked_files() -> list[str]:
    output = subprocess.check_output(
        ["git", "ls-files"], cwd=ROOT, text=True, encoding="utf-8"
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def _command_decorators(path: pathlib.Path) -> list[str]:
    if not path.exists():
        return ["fichier absent"]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            try:
                rendered = ast.unparse(decorator)
            except Exception:
                rendered = ""
            if rendered.startswith(("commands.command", "commands.hybrid_command", "commands.group", "commands.hybrid_group")):
                found.append(f"{node.name}: {rendered}")
    return found


def main() -> int:
    errors: list[str] = []
    tracked = _tracked_files()

    compiled = sorted(
        path for path in tracked
        if "/__pycache__/" in f"/{path}" or path.endswith((".pyc", ".pyo", ".pyd"))
    )
    if compiled:
        errors.append("fichiers Python compilés suivis par Git: " + ", ".join(compiled[:25]))

    obsolete = {
        "cogs/gamble_parser_fix.py",
    }
    returned = sorted(obsolete & set(tracked))
    if returned:
        errors.append("patchs obsolètes réintroduits: " + ", ".join(returned))

    for module in NO_COMMAND_MODULES:
        try:
            decorators = _command_decorators(module)
        except (OSError, SyntaxError) as exc:
            errors.append(f"audit impossible {module.name}: {type(exc).__name__}: {exc}")
            continue
        if decorators:
            errors.append(
                f"{module.relative_to(ROOT)} doit ajouter 0 commande publique: " + "; ".join(decorators)
            )

    gitignore = ROOT / ".gitignore"
    if not gitignore.exists():
        errors.append(".gitignore absent")
    else:
        text = gitignore.read_text(encoding="utf-8")
        for marker in ("__pycache__/", "*.py[cod]"):
            if marker not in text:
                errors.append(f".gitignore ne protège pas {marker}")

    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"ECHEC DETTE RUNTIME: {len(errors)} problème(s)")
        return 1

    print("OK DETTE RUNTIME: aucun bytecode suivi, aucun patch obsolète, 0 commande dans les couches transversales")
    return 0


if __name__ == "__main__":
    sys.exit(main())
