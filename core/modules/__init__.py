"""Registre central des modules SentriX — Milestone 2 (Configuration Platform).

Voir registry.py pour le contrat et definitions.py pour les modules réels
enregistrés aujourd'hui.
"""
from .registry import (
    ModuleDefinition,
    ModuleStatus,
    all_modules,
    all_statuses,
    get_definition,
    register,
    reset_for_tests,
    status_for,
    unregister,
)

__all__ = [
    "ModuleDefinition",
    "ModuleStatus",
    "all_modules",
    "all_statuses",
    "get_definition",
    "register",
    "reset_for_tests",
    "status_for",
    "unregister",
]
