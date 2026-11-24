"""Régression CI : la liste des commandes retirées doit être initialisée.

Le test vérifie la provenance et l'ordre de définition par AST, sans charger
Discord ni démarrer de bot ; un nom non défini faisait annuler 5 pipelines.
"""
from __future__ import annotations

import ast
from pathlib import Path

from cogs import command_catalog_cleanup


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools" / "command_runtime_audit.py"


def test_explicit_removed_defined_before_first_read():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    run = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run"
    )
    assignments = [
        node for node in ast.walk(run)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "explicit_removed"
            for target in node.targets
        )
    ]
    references = [
        node for node in ast.walk(run)
        if isinstance(node, ast.Name)
        and node.id == "explicit_removed"
        and isinstance(node.ctx, ast.Load)
    ]
    assert len(assignments) == 1
    assert references
    assert assignments[0].lineno < min(ref.lineno for ref in references)
    init = assignments[0].value
    assert isinstance(init, ast.Attribute)
    assert isinstance(init.value, ast.Name)
    assert init.value.id == "command_catalog_cleanup"
    assert init.attr == "EXPLICITLY_REMOVED_COMMANDS"


def test_explicit_removals_are_part_of_pruned_contract():
    assert command_catalog_cleanup.EXPLICITLY_REMOVED_COMMANDS <= (
        command_catalog_cleanup.INTENTIONALLY_REMOVED_COMMANDS
    )
    assert command_catalog_cleanup.PURE_DUPLICATE_COMMANDS <= (
        command_catalog_cleanup.INTENTIONALLY_REMOVED_COMMANDS
    )
