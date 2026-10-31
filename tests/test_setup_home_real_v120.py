"""Contrat de l'accueil SentriX : compact et privé, sans bascule rapide."""
from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "cogs" / "setup_experience_v74.py"


def _method(name):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == "SentriXSetupV74")
    method = next(x for x in cls.body if isinstance(x, ast.AsyncFunctionDef) and x.name == name)
    return ast.unparse(method)


def test_single_menu_covers_essential_setup_and_advanced_options():
    home = _method("_build_home")
    for word in ("security", "logs", "tickets", "welcome", "rules_access",
                 "custom_commands", "recurring_messages", "automation", "embeds"):
        assert word in home
    assert home.count("discord.ui.Select(") == 1
    assert "assert len(modules) <= 25" in home
    assert "self.refresh(interaction)" in home


def test_opening_a_page_never_activates_module():
    home = _method("_build_home")
    assert "toggle_module_switch" not in home
    assert "set_module_enabled" not in home
    assert "_set_security_profile" not in home


def test_guide_and_language_remain_reachable():
    home = _method("_build_home")
    assert "guided" in home
    assert "language" in home
    assert "OfficialLanguageSelect" in home


def test_setup_is_private_and_prefix_does_not_expose_controls():
    text = SOURCE.read_text(encoding="utf-8")
    start = text.index("async def _send_setup_v74(")
    end = text.index("\ndef install(", start)
    send = text[start:end]
    assert "ephemeral=True" in send
    assert "delete_after=15" in send
    assert "Utilise" not in send or "/setup" in send
    assert "return await target.send(" in send
