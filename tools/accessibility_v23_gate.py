#!/usr/bin/env python3
"""Gate statique de l'accessibilité SentriX V2.3."""
from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> int:
    errors: list[str] = []
    files = [
        "utils/accessibility.py",
        "cogs/sentrix_accessibility.py",
        "web/dashboard_accessibility.py",
        "cogs/final_runtime_polish.py",
        "tests/test_accessibility.py",
    ]
    for rel in files:
        path = ROOT / rel
        if not path.exists():
            errors.append(f"fichier absent: {rel}")
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as exc:
            errors.append(f"syntaxe invalide {rel}: {exc}")

    runtime = (ROOT / "cogs/sentrix_accessibility.py").read_text(encoding="utf-8")
    for marker in ("@commands.command", "@commands.hybrid_command", "@commands.group"):
        if marker in runtime:
            errors.append(f"la V2.3 ne doit pas ajouter de commande: {marker}")
    for marker in ("CommandNotFound", "MissingRequiredArgument", "closest_commands", "match_quick_intent", "Précédent", "Suivant"):
        if marker not in runtime:
            errors.append(f"fonction accessibilité manquante: {marker}")

    dashboard = (ROOT / "web/dashboard_accessibility.py").read_text(encoding="utf-8")
    for marker in ("sx-skip-link", "focus-visible", "prefers-reduced-motion", "prefers-contrast", "forced-colors", "aria-label", "44px"):
        if marker not in dashboard:
            errors.append(f"accessibilité dashboard manquante: {marker}")

    finalizer = (ROOT / "cogs/final_runtime_polish.py").read_text(encoding="utf-8")
    for marker in ("SentriXAccessibility", "dashboard_accessibility.install"):
        if marker not in finalizer:
            errors.append(f"bootstrap V2.3 manquant: {marker}")

    if errors:
        for error in errors:
            print("[ERROR]", error)
        return 1
    print("OK: SentriX V2.3 accessibilité valide, 0 nouvelle commande")
    return 0


if __name__ == "__main__":
    sys.exit(main())
