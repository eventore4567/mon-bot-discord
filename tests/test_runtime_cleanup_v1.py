from __future__ import annotations

import ast
import inspect
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
        # La regle vise le RUNTIME : aucun module de production ne doit dependre d'un
        # coordinateur legacy. Un test ou un outil d'audit qui l'importe pour verifier
        # son contenu ne cree aucun couplage a l'execution.
        if path.parts and path.parts[0] in {"tests", "tools"}:
            continue
        try:
            relative_parts = path.relative_to(ROOT).parts
        except ValueError:
            relative_parts = ()
        if relative_parts and relative_parts[0] in {"tests", "tools"}:
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
    """Le transport officiel ne doit pas ressusciter la couche V34.

    final_interaction_policy ne reference plus community_v34 du tout : il repart de la
    methode Discord native (_unwrap) et repose son propre wrapper. Les deux morceaux
    utiles de V34 (watchdog slash, IA rapide) restent installes par community_v34.install,
    appele depuis runtime_quality_v25.
    """
    assert "community_v34" not in FINAL_INTERACTION
    assert "_unwrap(discord.abc.Messageable.send)" in FINAL_INTERACTION

    from cogs import community_v34
    install_source = inspect.getsource(community_v34.install)
    assert "_install_slash_watchdog_policy(bot)" in install_source
    assert "_install_fast_ai(bot)" in install_source

    quality = (ROOT / "cogs" / "runtime_quality_v25.py").read_text(encoding="utf-8")
    assert "community_v34.install(bot)" in quality


def test_single_setup_style_chain_is_documented_and_mobile_legacy_is_absent():
    setup_section = COGS_INIT.split("async def _install_configuration_critical_patches", 1)[1]
    setup_section = setup_section.split("async def _install_common_runtime", 1)[0]
    # La chaine de style du setup est passee a setup_oxyde_v69 ; setup_oxyde_style ne
    # sert plus que de table de metadonnees (STEP_META) a language_setup_finalizer.
    assert "install_language_setup_finalizer" in setup_section
    assert "setup_mobile_cleanup" not in setup_section
    # Un seul installateur de style de setup dans tout le chargeur.
    style_installers = [
        line for line in COGS_INIT.splitlines()
        if "_run_installer(" in line and "oxyde" in line.casefold()
    ]
    assert len(style_installers) == 1, style_installers
    assert "install_setup_oxyde_v69" in style_installers[0]
