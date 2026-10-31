"""Le vrai /setup est la façade V74, pas l'ancien panneau V119.

Ces tests évitent le retour d'une configuration automatique de plusieurs
protections et gardent les raccourcis visibles sans changer les paramètres.
"""
from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "cogs" / "setup_experience_v74.py"


def _home_source() -> str:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    classe = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == "SentriXSetupV74")
    method = next(x for x in classe.body if isinstance(x, ast.AsyncFunctionDef) and x.name == "_build_home")
    return ast.unparse(method)


def test_home_has_shortcuts_for_core_setup():
    home = _home_source()
    for word in ("1. Sécurité", "2. Logs", "3. Tickets", "Bienvenue"):
        assert word in home
    assert "ouvrir_rapide" in home
    assert "self._new_backend(category)" in home
    assert "self.refresh(interaction)" in home


def test_opening_empty_security_never_bulk_enables_protections():
    home = _home_source()
    assert "switch_states.get(module) == 'empty'" in home
    assert "self.page = 'security'" in home
    assert "self._set_security_profile(" not in home
    assert "toggle_module_switch" in home


def test_advanced_configuration_remains_available():
    home = _home_source()
    for page in ("rules_access", "custom_commands", "recurring_messages", "automation", "embeds"):
        assert page in home
    assert "Configuration guidée" in home
