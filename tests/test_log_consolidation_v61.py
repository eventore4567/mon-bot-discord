from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "cogs" / "log_consolidation_v61.py"
RUNTIME = ROOT / "cogs" / "command_no_emoji_runtime.py"


def test_v61_source_exists_and_compiles() -> None:
    source = MODULE.read_text(encoding="utf-8")
    ast.parse(source, filename=str(MODULE))
    assert "channel_create" in source
    assert "channel_delete" in source
    assert "channel_update" in source
    assert "categorie modifiee" in source
    assert "Réorganisation liée" in source


def test_v61_keeps_real_updates() -> None:
    source = MODULE.read_text(encoding="utf-8")
    # Une update de nom/sujet ne doit jamais être absorbée avec un delete/create voisin.
    for marker in ("\"nom\"", "sujet modifie", "permissions modifie", "slowmode", "nsfw"):
        assert marker in source


def test_channel_target_is_not_rendered_twice() -> None:
    source = MODULE.read_text(encoding="utf-8")
    start = source.index("def _single_channel_display")
    end = source.index("\ndef _install_single_target_renderer", start)
    function = source[start:end]
    assert 'return f"{channel.mention} · `{channel.id}`"' in function
    assert "channel.mention} · **#" not in function


def test_v61_is_installed_after_identity_fix() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    identity = source.index("install_log_identity_context_v60(bot)")
    consolidation = source.index("install_log_consolidation_v61(bot)")
    assert identity < consolidation
