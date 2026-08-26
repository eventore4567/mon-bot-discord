"""Garde-fou indépendant : aucune invitation ne peut être créée automatiquement à l'arrivée."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "cogs" / "owner_log_rebuild.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)

owner_cog = next(
    node for node in TREE.body
    if isinstance(node, ast.ClassDef) and node.name == "OwnerLogRebuild"
)
on_join = next(
    node for node in owner_cog.body
    if isinstance(node, ast.AsyncFunctionDef) and node.name == "on_guild_join"
)
button_view = next(
    node for node in TREE.body
    if isinstance(node, ast.ClassDef) and node.name == "SetupHelpView"
)
button_callback = next(
    node for node in button_view.body
    if isinstance(node, ast.AsyncFunctionDef) and node.name == "request_help"
)

join_source = ast.get_source_segment(SOURCE, on_join) or ""
button_source = ast.get_source_segment(SOURCE, button_callback) or ""

assert "create_invite" not in join_source
assert "_create_and_deliver_help_invite" in button_source
assert "administrator" in button_source
assert "manage_guild" in button_source

print("owner log rebuild secret-invite guard: OK")
