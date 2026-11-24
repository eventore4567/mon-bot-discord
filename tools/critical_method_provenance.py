#!/usr/bin/env python3
"""Observe l'implémentation effective de méthodes critiques APRÈS le boot E2E.

Lecture seule : aucune méthode n'est patchée. Le résultat signale les
remplacements sans lien *observable* vers le code original, mais ne prétend
pas prouver qu'ils sont incorrects : un wrapper peut déléguer autrement.
Ne lance ni Discord Gateway ni le token de production.
"""
from __future__ import annotations

import asyncio
import ast
import importlib
import inspect
import json
import pathlib
from collections import deque

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Contrat statique des points critiques, distinct des implémentations
# réellement chargées et modifiées par les installateurs.
TARGETS = (
    ("cogs.automod", "AutoMod", "_upsert_native_rule"),
    ("cogs.tickets", "Tickets", "close_ticket"),
    ("cogs.tickets", "Tickets", "_auto_delete"),
)


def original_definition(root: pathlib.Path, module: str, cls: str, method: str):
    path = root.joinpath(*module.split(".")).with_suffix(".py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != cls:
            continue
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method:
                return path.resolve(), child.lineno
    raise LookupError(f"Original method not declared: {module}.{cls}.{method}")


def source_identity(callback) -> tuple[str | None, int | None]:
    fn = callback.__func__ if inspect.ismethod(callback) else callback
    code = getattr(fn, "__code__", None)
    if code is None:
        return None, None
    try:
        return str(pathlib.Path(code.co_filename).resolve()), int(code.co_firstlineno)
    except (OSError, ValueError, TypeError):
        return None, None


def linked_functions(callback):
    """Liens explicites ET fonctions capturées dans une fermeture.

    Le code appelé par une fermeture n'est pas nécessairement exécuté :
    le résultat reste un indice de provenance, non une preuve fonctionnelle.
    """
    queue = deque([callback])
    visited = set()
    while queue and len(visited) < 48:
        fn = queue.popleft()
        fn = fn.__func__ if inspect.ismethod(fn) else fn
        if not inspect.isfunction(fn) or id(fn) in visited:
            continue
        visited.add(id(fn))
        yield fn
        for attr in ("__wrapped__", "_sentrix_original"):
            link = getattr(fn, attr, None)
            if inspect.isfunction(link) or inspect.ismethod(link):
                queue.append(link)
        for cell in getattr(fn, "__closure__", ()) or ():
            try:
                value = cell.cell_contents
            except ValueError:
                continue
            if inspect.isfunction(value) or inspect.ismethod(value):
                queue.append(value)


def inspect_effective_method(cls, method: str, expected_file: pathlib.Path, expected_line: int) -> dict:
    current = getattr(cls, method, None)
    if current is None:
        return {"status": "missing", "replaced": True, "original_linked": False}
    current_source, current_line = source_identity(current)
    expected = (str(expected_file.resolve()), int(expected_line))
    replaced = (current_source, current_line) != expected
    linked = any(source_identity(fn) == expected for fn in linked_functions(current))
    if not replaced:
        status = "original"
    elif linked:
        status = "wrapped_original_reachable"
    else:
        status = "replacement_without_observable_original_link"
    return {
        "status": status,
        "replaced": replaced,
        "original_linked": linked,
        "effective_source": current_source,
        "effective_line": current_line,
        "expected_source": expected[0],
        "expected_line": expected[1],
    }


def snapshot(root: pathlib.Path = ROOT) -> dict:
    results = {}
    for module_name, class_name, method_name in TARGETS:
        key = f"{module_name}.{class_name}.{method_name}"
        try:
            expected_file, expected_line = original_definition(root, module_name, class_name, method_name)
            module = importlib.import_module(module_name)
            cls = getattr(module, class_name)
            results[key] = inspect_effective_method(cls, method_name, expected_file, expected_line)
        except (ImportError, AttributeError, LookupError, SyntaxError, OSError) as exc:
            results[key] = {"status": "unavailable", "error_type": type(exc).__name__}
    return {
        "scope": "after offline E2E bootstrap; without on_ready or live Discord events",
        "interpretation": "provenance only, not proof of functional defect",
        "methods": results,
    }


async def _boot_and_snapshot() -> dict:
    # Ne pas importer le harnais en tête de module : il modifie volontairement
    # l'environnement pour isoler les appels sortants durant les tests E2E.
    from tools import sentrix_e2e_harness as harness

    bot = await harness.boot(quiet=False)
    try:
        return snapshot()
    finally:
        await bot.close()


def main() -> int:
    report = asyncio.run(_boot_and_snapshot())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # Ne pas bloquer la CI sur un remplacement volontaire : seul un test de
    # comportement indépendant peut établir qu'un wrapper est défaillant.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
