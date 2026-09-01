from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "cogs" / "setup_simple_v68.py"
LOADER = ROOT / "cogs" / "__init__.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_v68_compiles() -> None:
    source = _source(MODULE)
    ast.parse(source, filename=str(MODULE))
    assert "Setup simplifié V68" in source


def test_permissions_page_has_one_simple_toggle() -> None:
    source = _source(MODULE)
    start = source.index("def render_v68")
    end = source.index("async def build_embed_v68", start)
    render = source[start:end]
    assert 'label="Activer / Désactiver"' in render
    assert "SafePermissionRoleSelect" not in render
    assert "SafePermissionScopeSelect" not in render
    assert "SafePermissionCommandSelect" not in render
    assert "_remove_controls_except_navigation" in render


def test_disabling_sentrix_acl_never_disables_native_discord_permissions() -> None:
    source = _source(MODULE)
    tree = ast.parse(source)
    fn = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "secure_evaluate_v68"
    )
    text = ast.unparse(fn)
    # ast.unparse re-emet les litteraux avec des guillemets simples.
    assert "core.module_enabled(bot, guild_id, 'permissions')" in text
    assert "backend.explicit_rule" in text
    assert "matrix.DISCORD_PERMISSION_COMMANDS" in text
    assert "_has_native_permission" in text
    assert "matrix.OWNER_ONLY_COMMANDS" in text


def test_all_setup_embeds_are_widened() -> None:
    source = _source(MODULE)
    assert "SETUP_WIDE_BAR" in source
    assert "panel = await previous_build_embed(self)" in source
    assert "return _wide_embed(panel)" in source


def test_help_v68_is_wide_and_mentions_simple_setup() -> None:
    source = _source(MODULE)
    assert "def home_v68" in source
    assert "Permissions" in source
    assert "Sécurité" in source
    assert "Activer / Désactiver" in source
    assert "panel.set_thumbnail(url=None)" in source
    assert "inline=True" in source


def test_v68_loads_after_v66() -> None:
    source = _source(LOADER)
    v66 = source.index("install_permission_setup_hardening_v65")
    # L'import apparaît avant finalize_runtime ; on veut comparer les appels dans la
    # section finale, pas les lignes d'import.
    final = source.index("async def finalize_runtime")
    v66_call = source.index("install_permission_setup_hardening_v65", final)
    v68_call = source.index("install_setup_simple_v68", final)
    assert v66 < final
    assert v66_call < v68_call


def test_permissions_toggle_keeps_saved_restrictions() -> None:
    source = _source(MODULE)
    start = source.index("async def permissions_toggle_cb")
    end = source.index("toggle.callback", start)
    callback = source[start:end]
    assert "set_module_enabled" in callback
    assert "DELETE FROM command_role_permissions" not in callback


def test_help_lists_staff_commands_without_granting_permissions() -> None:
    source = _source(MODULE)
    assert "Les commandes staff restent visibles" in source
    assert "permission Discord" in source
