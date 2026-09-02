"""Integration de la diffusion privee dans le demarrage reel de SentriX."""

import ast
from pathlib import Path

from utils import access_matrix as M


ROOT = Path(__file__).resolve().parents[1]


def test_dmall_extension_is_loaded_by_main():
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    extensions = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "EXTENSIONS" for target in node.targets):
            extensions = ast.literal_eval(node.value)
            break

    assert extensions is not None
    assert "sentrix_broadcast_dmall_visual" in extensions


def test_dmall_is_classified_as_guild_owner_only():
    assert "dmall" in M.KNOWN_COMMANDS
    assert "dmall" in M.GUILD_OWNER_COMMANDS
    assert M.access_tier("dmall") == "guild-owner"
    assert M.help_requirement("dmall") == "Propriétaire du serveur uniquement"


def test_dmall_cog_keeps_the_required_safety_controls():
    source = (ROOT / "sentrix_broadcast_dmall_visual.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert 'name="dmall"' in source
    assert "if not member.bot" in source
    assert "active_guilds" in source
    assert "await asyncio.sleep(SEND_DELAY_SECONDS)" in source
    assert any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "setup"
        for node in ast.walk(tree)
    )
