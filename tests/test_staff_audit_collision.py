"""Contrats de non-collision des commandes staff de SentriX.

Cette extension était totalement refusée à l'initialisation car elle redéclarait
/audit. Garder un nom propre pour le diagnostic staff, sans retirer le panneau.
"""
from __future__ import annotations

import ast
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "cogs" / "staff_suite.py"


def _hybrid_command_names():
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    suite = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "StaffSuite")
    registered = {}
    for method in suite.body:
        if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in method.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if not isinstance(decorator.func, ast.Attribute) or decorator.func.attr != "hybrid_command":
                continue
            name_argument = next((item.value for item in decorator.keywords if item.arg == "name"), None)
            if isinstance(name_argument, ast.Constant) and isinstance(name_argument.value, str):
                registered[name_argument.value] = method
    return registered


def test_staff_suite_does_not_redeclare_global_audit():
    commands = _hybrid_command_names()
    assert "audit" not in commands, "Un deuxième /audit empêche le chargement du cog staff"
    assert "staff-diagnostic" in commands


def test_staff_diagnostic_still_displays_the_existing_audit_panel():
    commands = _hybrid_command_names()
    method = commands["staff-diagnostic"]
    source = ast.unparse(method)
    assert "self.audit_panel(ctx.guild)" in source
    assert 'is_owner_or_admin_for("configuration")' in source
