from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "cogs" / "sentrix_emoji_runtime.py"
HELP_COMPAT = ROOT / "cogs" / "help_cooldown_exemption_v3.py"
GLOBAL_STYLE = ROOT / "cogs" / "sentrix_v3_global_style.py"
ASSET_DIR = ROOT / "assets" / "sentrix_emojis"

EXPECTED = {
    "sentrix_loading.gif",
    "sentrix_ok.gif",
    "sentrix_error.gif",
    "sentrix_no.gif",
    "sentrix_alert.gif",
    "sentrix_ticket.gif",
    "sentrix_staff.gif",
    "sentrix_update.gif",
    "sentrix_online.gif",
    "sentrix_premium.gif",
}
PACK_PREFIX = "sxv37_"


def test_v36_pack_contains_nine_real_animated_gifs() -> None:
    found = {path.name for path in ASSET_DIR.glob("*.gif")}
    assert found == EXPECTED
    for path in ASSET_DIR.glob("*.gif"):
        payload = path.read_bytes()
        assert payload[:6] in {b"GIF87a", b"GIF89a"}
        # NETSCAPE2.0 est l'extension de boucle utilisée par les GIFs animés du pack.
        assert b"NETSCAPE2.0" in payload
        assert 0 < len(payload) < 256_000


def test_v36_runtime_never_adds_commands_or_deletes_server_emojis() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"command", "hybrid_command", "group", "hybrid_group"}
    for node in ast.walk(tree):
        for decorator in getattr(node, "decorator_list", []):
            name = ""
            if isinstance(decorator, ast.Call):
                decorator = decorator.func
            if isinstance(decorator, ast.Attribute):
                name = decorator.attr
            elif isinstance(decorator, ast.Name):
                name = decorator.id
            assert name not in forbidden

    assert "create_custom_emoji" in source
    assert "len(PACK)" in source

    # Le runtime nettoie l'ancien pack du bot avant d'installer le nouveau. Cette
    # suppression doit rester strictement bornee : seuls les emojis crees par une
    # version precedente de SentriX, reconnus a leur prefixe, peuvent partir.
    from cogs import sentrix_emoji_runtime as runtime

    assert runtime.LEGACY_PACK_PREFIXES, "aucun prefixe : la suppression serait ouverte"
    for prefix in runtime.LEGACY_PACK_PREFIXES:
        assert prefix.startswith("sxv"), prefix
        assert prefix != PACK_PREFIX, "le pack courant ne doit jamais s'auto-supprimer"

    for name in ("general", "custom", "cat", "sxv37_ok", ""):
        assert runtime._is_legacy_pack_emoji_name(name) is False, name
    assert runtime._is_legacy_pack_emoji_name("sxv36_ok") is True

    # Aucune suppression hors de _delete_legacy_pack.
    tree_del = [
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and ".delete(" in ast.unparse(node)
    ]
    assert {node.name for node in tree_del} == {"_delete_legacy_pack"}


def test_v36_pack_has_exact_semantic_registry() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    for key in ("loading", "ok", "error", "no", "alert", "ticket",
                "staff", "update", "online", "premium"):
        assert f'"{key}": ("{PACK_PREFIX}{key}"' in source


def test_v36_is_reasserted_after_historical_v2_renderer() -> None:
    source = HELP_COMPAT.read_text(encoding="utf-8")
    assert "global_style._INSTALLED = False" in source
    assert "animated._INSTALLED = False" in source
    assert "global_style.install(bot)" in source
    assert "_install_final_visuals(bot)" in source


def test_help_replaces_legacy_component_emojis_with_v36_pack() -> None:
    source = HELP_COMPAT.read_text(encoding="utf-8")
    assert "item.emoji = None" in source
    assert "option.emoji = None" in source
    assert "animated._decorate_view(view)" in source
    assert "animated._decorate_embed(embed" in source
    assert "_sentrix_animated_help_v36" in source


def test_v34_installs_v36_after_two_size_layout() -> None:
    source = GLOBAL_STYLE.read_text(encoding="utf-8")
    layout = source.index("_apply_two_size_layout(embed, size=size)")
    v36_import = source.index("from .sentrix_emoji_runtime import install as install_animated_emoji_pack")
    v36_call = source.index("install_animated_emoji_pack(bot)")
    assert layout < v36_import < v36_call
