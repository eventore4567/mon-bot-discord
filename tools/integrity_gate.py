#!/usr/bin/env python3
"""Quality gate ciblé sur les régressions trouvées pendant l'audit A→Z SentriX."""
from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> int:
    errors: list[str] = []
    integrity_path = ROOT / "cogs" / "integrity_hardening.py"
    stats_path = ROOT / "cogs" / "stats.py"

    if not integrity_path.exists():
        errors.append("cogs/integrity_hardening.py absent")
    else:
        text = integrity_path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=str(integrity_path))
        except SyntaxError as exc:
            errors.append(f"syntaxe integrity_hardening invalide: {exc}")
            tree = None

        # Cette couche doit rester un durcissement, pas devenir une nouvelle source de commandes.
        for marker in ("@commands.command", "@commands.hybrid_command", "@commands.group", "@commands.hybrid_group"):
            if marker in text:
                errors.append(f"commande publique ajoutée dans integrity_hardening: {marker}")

        required_markers = (
            "root_name.casefold() != str(requested_name).casefold()",
            "AND quantity>=1",
            "AND cash>=?",
            "AND bank>=?",
            "_sentrix_integrity_tempaction_task",
            "Cette action est réservée au staff du ticket.",
            "status='supprime' WHERE id=? AND status='ferme'",
            "_ExpiringPlayLockRegistry",
            '"new_commands": 0',
        )
        for marker in required_markers:
            if marker not in text:
                errors.append(f"garantie d'intégrité absente: {marker}")

        if tree is not None:
            public_decorators = 0
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for dec in node.decorator_list:
                    rendered = ast.unparse(dec) if hasattr(ast, "unparse") else ""
                    if rendered.startswith("commands."):
                        public_decorators += 1
            if public_decorators:
                errors.append(f"{public_decorators} décorateur(s) commands.* inattendu(s)")

    if not stats_path.exists():
        errors.append("cogs/stats.py absent")
    else:
        stats_text = stats_path.read_text(encoding="utf-8")
        if "integrity_hardening.install(bot)" not in stats_text:
            errors.append("integrity_hardening n'est pas branché au démarrage")

    # Le pruning historique reste présent, mais sa méthode est remplacée avant son appel.
    main_path = ROOT / "main.py"
    if main_path.exists():
        main_text = main_path.read_text(encoding="utf-8")
        if "self._prune_redundant_commands()" not in main_text:
            errors.append("appel de pruning principal introuvable")

    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"ECHEC INTEGRITE: {len(errors)} problème(s)")
        return 1

    print("OK INTEGRITE: pruning, économie, modération, tickets et jeux durcis; 0 nouvelle commande")
    return 0


if __name__ == "__main__":
    sys.exit(main())
