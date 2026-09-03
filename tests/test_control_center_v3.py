from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "cogs" / "control_center_v3.py"
RUNTIME = ROOT / "cogs" / "__init__.py"
LANGUAGE = ROOT / "cogs" / "control_center_v3_language.py"
AI = ROOT / "cogs" / "ai.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_control_center_v3_is_valid_python_and_has_one_final_installer():
    source = _source(CONTROL)
    ast.parse(source)
    assert "async def install(bot: commands.Bot)" in source
    assert "_sentrix_control_center_v3_installed" in source
    assert "_install_setup_v3(bot)" in source
    assert "_install_honeypot_runtime(bot)" in source
    assert "_install_self_role_backend(bot)" in source


def test_setup_v3_uses_large_pages_and_single_module_toggle_contract():
    source = _source(CONTROL)
    assert "class V3CategorySelect" in source
    assert "class ModuleToggle" in source
    assert 'label="Désactiver" if enabled else "Activer"' in source
    assert 'value="security_verification"' in source
    assert 'value="roles_panel"' in source
    assert "cls.render = _v3_render" in source
    assert "cls.build_embed = _v3_build_embed" in source
    # Les anciens boutons de navigation ne doivent plus être recréés par le renderer V3.
    render_section = source[source.index("def _v3_render"):source.index("async def _v3_build_embed")]
    assert 'discord.ui.Button(label="Accueil"' not in render_section
    assert 'discord.ui.Button(label="Actualiser"' not in render_section
    assert 'discord.ui.Button(label="Fermer"' not in render_section


def test_honeypot_reuses_the_existing_strong_v50_engine():
    source = _source(CONTROL)
    assert "honeypot_verification_v48 as honeypot_v50" in source
    assert "HoneypotVerification(bot)" in source
    assert "create_or_refresh_system" in source
    assert "disable_system" in source
    assert not (ROOT / "cogs" / "security_verification_v3.py").exists()


def test_render_member_template_placeholders_still_defined_here():
    # Bienvenue/depart ne sont plus envoyes depuis ce fichier (voir
    # tests/test_welcome_single_source_of_truth.py) mais render_member_template reste ici,
    # reutilise par cogs/setup_v2_completion.py — seul emetteur desormais.
    source = _source(CONTROL)
    for placeholder in (
        "{member}", "{membre}", "{mention}", "{user}", "{username}",
        "{display_name}", "{server}", "{serveur}", "{member_count}",
    ):
        assert placeholder in source


def test_role_choice_panel_is_explicitly_configurable():
    source = _source(CONTROL)
    assert "self_role_setup_v3" in source
    assert "self_role_items" in source
    assert "RolePanelChannelSelect" in source
    assert "RolePanelRolesSelect" in source
    assert "_publish_or_refresh_role_panel" in source
    assert "_sentrix_control_center_v3_roles" in source


def test_success_error_semantics_and_achievement_copy_are_guarded():
    source = _source(CONTROL)
    assert "def semantic_kind" in source
    assert "_DANGER_RE.search(text)" in source
    assert "_SUCCESS_RE.search(text)" in source
    # Le cas qui avait tendance à être mal classé : « débloqué » ne doit pas matcher « bloqué ».
    assert "d[ée]bloqu" in source
    assert "succès débloqué" in source.casefold()
    assert "_sentrix_control_center_v3_achievements" in source


def test_canonical_ai_still_handles_sentrix_name_trigger_without_prototype():
    source = _source(AI)
    assert "name_trigger = name_match is not None" in source
    assert "if not mentioned and not name_trigger" in source
    assert "await self.send_sentrix_reply" in source
    assert not (ROOT / "cogs" / "ai_bare_chat_v3.py").exists()


def test_final_runtime_installs_v3_after_official_help_and_then_language():
    source = _source(RUNTIME)
    assert "install_control_center_v3" in source
    assert "install_control_center_v3_language" in source
    help_pos = source.index("await _load_official_help(bot)")
    control_pos = source.index('await _run_installer("Control Center V3"', help_pos)
    language_pos = source.index('await _run_installer("langue Control Center V3"', control_pos)
    assert help_pos < control_pos < language_pos


def test_language_bridge_targets_final_v3_renderer():
    source = _source(LANGUAGE)
    ast.parse(source)
    assert "OfficialLanguageSelect" in source
    assert "_sentrix_control_center_v3_language" in source
    assert "current_render(self)" in source
    assert "current_build_embed(self)" in source
    # Le pont historique peut déjà avoir posé le sélecteur : V3 doit le réutiliser.
    assert "has_language_select = any(" in source
    assert "if not has_language_select:" in source
