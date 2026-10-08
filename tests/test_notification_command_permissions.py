"""Regression de permissions : diagnostics des notifications sociales.

Un command handler decoré admin qui reste non-classé devient fail-closed
(ce qui casse aussi sa découvrabilité dans l'aide). Le correctif ne doit
pas rendre ces diagnostics accessibles à tous.
"""
from __future__ import annotations

import ast
from pathlib import Path

from utils import access_matrix


ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTICS = ("notifs-status", "notifs-test")


def test_social_diagnostics_have_explicit_configuration_tier():
    for name in DIAGNOSTICS:
        assert name in access_matrix.KNOWN_COMMANDS
        assert name in access_matrix.CATEGORY_COMMANDS["configuration"]
        assert name not in access_matrix.PUBLIC_COMMANDS
        assert access_matrix.access_tier(name) == "categorie:configuration"


def test_main_catalog_matches_authoritative_configuration_tier():
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    decl = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "CATEGORY_COMMANDS" for t in node.targets)
    )
    names = {
        node.value for node in ast.walk(decl.value)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert set(DIAGNOSTICS) <= names


def test_callbacks_keep_admin_check_and_prefix_only():
    tree = ast.parse((ROOT / "cogs" / "notifications.py").read_text(encoding="utf-8"))
    methods = {
        method.name: method
        for cls in ast.walk(tree)
        if isinstance(cls, ast.ClassDef)
        for method in cls.body
        if isinstance(method, (ast.AsyncFunctionDef, ast.FunctionDef))
    }
    for method_name in ("notifs_status", "notifs_test"):
        method = methods[method_name]
        decorators = [ast.unparse(x) for x in method.decorator_list]
        assert any('is_owner_or_admin_for("configuration")' in x for x in decorators)
        assert any("with_app_command=False" in x for x in decorators)
