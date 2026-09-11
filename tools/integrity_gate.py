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
    # Core V2, Phase 4 : les trois garanties atomiques économie (dépôt/retrait,
    # vente) ont été extraites de integrity_hardening.py vers services/economy.py
    # (comportement inchangé, vérifié par tests/test_services_economy.py) — ce
    # gate cherchait encore ces marqueurs dans l'ancien fichier et échouait donc
    # à tort depuis cette extraction, sans que personne ne le remarque puisqu'il
    # n'était jamais exécuté en CI.
    economy_path = ROOT / "services" / "economy.py"

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
            "_sentrix_integrity_tempaction_task",
            "Cette action est réservée au staff du ticket.",
            "status='supprime' WHERE id=? AND status='ferme'",
            "_ExpiringPlayLockRegistry",
            '"new_commands": 0',
        )
        for marker in required_markers:
            if marker not in text:
                errors.append(f"garantie d'intégrité absente: {marker}")

        if not economy_path.exists():
            errors.append("services/economy.py absent")
        else:
            economy_text = economy_path.read_text(encoding="utf-8")
            for marker in ("AND quantity>=1", "AND cash>=?", "AND bank>=?"):
                if marker not in economy_text:
                    errors.append(f"garantie d'intégrité économie absente (services/economy.py): {marker}")

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
