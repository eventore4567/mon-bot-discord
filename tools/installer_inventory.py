#!/usr/bin/env python3
"""Inventaire NON DESTRUCTIF des installateurs SentriX.

Une fonction install() sans setup() n'est PAS nécessairement du code mort :
elle peut être appelée par un orchestrateur (V17/V95/Railway). Cet outil
énumère les candidats à vérifier sans jamais les supprimer ni les importer.
L'audit d'exécution réel doit être réalisé séparément avant de conclure.
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def entrypoints(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {"setup", "install"}
    }


def declared_extensions(root: pathlib.Path) -> set[str]:
    """Lit les extensions explicites main.py + railway_boot.py par AST."""
    result: set[str] = set()
    main_file = root / "main.py"
    if main_file.exists():
        tree = ast.parse(main_file.read_text(encoding="utf-8"), filename=str(main_file))
        for node in tree.body:
            value = None
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "EXTENSIONS"
                for target in node.targets
            ):
                value = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "EXTENSIONS":
                value = node.value
            if isinstance(value, (ast.List, ast.Tuple)):
                result.update(
                    item.value for item in value.elts
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                )

    boot_file = root / "railway_boot.py"
    if boot_file.exists():
        tree = ast.parse(boot_file.read_text(encoding="utf-8"), filename=str(boot_file))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or len(node.args) != 1:
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "append":
                continue
            target = func.value
            if not (
                isinstance(target, ast.Attribute)
                and target.attr == "EXTENSIONS"
                and isinstance(target.value, ast.Name)
                and target.value.id == "bot_main"
            ):
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                result.add(arg.value)
    return result


def inventory(root: pathlib.Path = ROOT) -> dict:
    extensions = declared_extensions(root)
    entries: list[dict[str, object]] = []
    for path in sorted((root / "cogs").glob("*.py")):
        functions = entrypoints(path)
        if not functions:
            continue
        module = f"cogs.{path.stem}"
        entries.append({
            "module": module,
            "has_setup": "setup" in functions,
            "has_install": "install" in functions,
            "declared_as_extension": module in extensions,
        })

    unknown_extensions = sorted(
        name for name in extensions
        if name.startswith("cogs.") and not (
            root / "cogs" / (name.removeprefix("cogs.") + ".py")
        ).is_file()
    )
    return {
        "declared_extension_count": len(extensions),
        "install_without_setup": sorted(
            str(row["module"]) for row in entries
            if row["has_install"] and not row["has_setup"]
        ),
        "setup_not_declared_as_extension": sorted(
            str(row["module"]) for row in entries
            if row["has_setup"] and not row["declared_as_extension"]
        ),
        "declared_extensions_without_setup": sorted(
            str(row["module"]) for row in entries
            if row["declared_as_extension"] and not row["has_setup"]
        ),
        "unknown_extension_modules": unknown_extensions,
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Imprimer le rapport JSON complet.")
    args = parser.parse_args()
    report = inventory()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Extensions déclarées : {report['declared_extension_count']}")
        print(f"install() sans setup() : {len(report['install_without_setup'])} candidats à vérifier")
        print(f"setup() non déclaré en extension : {len(report['setup_not_declared_as_extension'])}")
        print(f"Extensions sans setup() : {len(report['declared_extensions_without_setup'])}")
        print(f"Fichiers de cogs manquants : {len(report['unknown_extension_modules'])}")
        print("\nInstallateurs manuels (ne pas supprimer sans trace d'exécution) :")
        for name in report["install_without_setup"]:
            print("  CANDIDAT", name)
        for name in report["unknown_extension_modules"]:
            print("  MODULE MANQUANT", name)
        print("\nAttention : non déclaré en extension ne signifie pas non exécuté.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
