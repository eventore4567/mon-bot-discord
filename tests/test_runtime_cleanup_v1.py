from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COGS_INIT = (ROOT / "cogs" / "__init__.py").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
GUILD_ARRIVAL = (ROOT / "cogs" / "guild_arrival.py").read_text(encoding="utf-8")
FINAL_INTERACTION = (ROOT / "cogs" / "final_interaction_policy.py").read_text(encoding="utf-8")
LEGACY_COORDINATORS = {
    "plain_response_policy.py": "plain_response_policy",
    "setup_mobile_cleanup.py": "setup_mobile_cleanup",
    "command_no_emoji_runtime.py": "command_no_emoji_runtime",
}


def _main_extensions() -> list[str]:
    tree = ast.parse(MAIN)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "EXTENSIONS" for target in node.targets):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            return []
        return [
            item.value for item in node.value.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        ]
    return []


def _external_imports(module_name: str, own_filename: str) -> list[str]:
    hits: list[str] = []
    import_needles = (
        f"from .{module_name} import",
        f"from cogs.{module_name} import",
        f"import cogs.{module_name}",
        f"from cogs import {module_name}",
    )
    for path in ROOT.rglob("*.py"):
        if path.name in {own_filename, Path(__file__).name}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if any(needle in text for needle in import_needles):
            hits.append(str(path.relative_to(ROOT)))
    return hits


def test_legacy_global_coordinators_are_out_of_active_runtime():
    assert "from .plain_response_policy" not in COGS_INIT
    assert "from .setup_mobile_cleanup" not in COGS_INIT
    assert "from .command_no_emoji_runtime" not in COGS_INIT
    assert "install_plain_response_policy" not in COGS_INIT
    assert "install_setup_mobile_cleanup" not in COGS_INIT
    assert "install_command_no_emoji" not in COGS_INIT


def test_legacy_coordinators_have_no_external_python_imports():
    leftovers = {
        module: _external_imports(module, filename)
        for filename, module in LEGACY_COORDINATORS.items()
    }
    assert leftovers == {module: [] for module in LEGACY_COORDINATORS.values()}


def test_global_runtime_is_finalized_once_at_end_of_extension_list():
    extensions = _main_extensions()
    assert extensions
    assert extensions[-1] == "cogs.visual_experience_v5"
    assert '_FINAL_EXTENSION = "cogs.visual_experience_v5"' in COGS_INIT
    assert "async def finalize_runtime" in COGS_INIT
    assert "if _matches(name, _FINAL_EXTENSION):\n        await finalize_runtime(bot)" in COGS_INIT


def test_extension_loader_no_longer_reapplies_global_style_stack_each_time():
    loader = COGS_INIT.split("async def _load_extension_with_sentrix_patches", 1)[1]
    loader = loader.split("if not getattr(commands.Bot", 1)[0]
    assert "_install_common_runtime(bot)" not in loader
    assert "_install_log_stack(bot)" not in loader
    assert "_install_help_and_error_stack(bot)" not in loader
    assert "install_final_interaction_policy" not in loader
    assert "await _install_extension_specific(bot, name)" in loader


def test_guild_arrival_does_not_install_global_style_anymore():
    assert "sentrix_v3_global_style" not in GUILD_ARRIVAL
    assert "install_global_style" not in GUILD_ARRIVAL


def test_final_interaction_does_not_reinstall_legacy_v34_transport():
    assert "community_v34.install(bot)" not in FINAL_INTERACTION
    assert "_install_v34_runtime_only(bot)" in FINAL_INTERACTION
    assert "community_v34._install_slash_watchdog_policy(bot)" in FINAL_INTERACTION
    assert "community_v34._install_fast_ai(bot)" in FINAL_INTERACTION


def test_single_setup_style_chain_is_documented_and_mobile_legacy_is_absent():
    setup_section = COGS_INIT.split("async def _install_configuration_critical_patches", 1)[1]
    setup_section = setup_section.split("async def _install_common_runtime", 1)[0]
    assert "install_setup_oxyde_style" in setup_section
    assert "install_language_setup_finalizer" in setup_section
    assert "setup_mobile_cleanup" not in setup_section
