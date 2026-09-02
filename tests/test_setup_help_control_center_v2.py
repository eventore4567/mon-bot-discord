from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_new_setup_is_real_runtime_owner():
    init_source = _source("cogs/__init__.py")
    setup_source = _source("cogs/setup_control_center.py")
    assert "install_setup_control_center" in init_source
    assert 'bot._sentrix_setup_owner = "cogs.setup_control_center"' in setup_source
    assert '@commands.command(name="setup")' in setup_source
    assert '@app_commands.command(name="setup"' in setup_source


def test_setup_has_requested_categories_and_states():
    source = _source("cogs/setup_control_center.py")
    for category in (
        "Modération", "Sécurité", "Logs", "Tickets", "Bienvenue & départ",
        "Rôles", "Niveaux & économie", "Notifications", "IA",
    ):
        assert category in source
    for state in ("ACTIF", "INACTIF", "NON CONFIGURÉ", "ERREUR DE CONFIGURATION"):
        assert state in source
    assert "_completion" in source
    # La section s'appelle maintenant « Permissions manquantes » et n'apparait que
    # s'il en manque vraiment : enumerer les « OK » noyait l'information utile.
    assert "Permissions manquantes" in source
    assert "BOT_PERMS" in source


def test_setup_edits_one_message_and_has_clear_navigation():
    source = _source("cogs/setup_control_center.py")
    assert "interaction.response.edit_message" in source
    assert 'placeholder="Choisir une catégorie"' in source
    assert 'label="Accueil"' in source
    assert 'label="Fermer"' in source


def test_help_never_hides_admin_commands_from_catalog():
    source = _source("cogs/help.py")
    tree = ast.parse(source)
    visible = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_visible")
    visible_source = ast.get_source_segment(source, visible)
    assert "STAFF_COGS" not in visible_source
    assert "guild_permissions" not in visible_source
    assert "command.hidden" in visible_source
    assert "Permission nécessaire" in source
    assert "command_example" in source


def test_help_supports_prefix_and_slash_direct_search():
    source = _source("cogs/help.py")
    assert '@commands.command(name="help"' in source
    assert '@app_commands.command(name="help"' in source
    assert "if query:" in source
    assert "_exact_match" in source


def test_server_managers_do_not_bypass_admin_permissions_anymore():
    checks_source = _source("utils/checks.py")
    guard_source = _source("cogs/permission_guard.py")
    # La décision d'accès vit désormais dans utils/access_matrix.py ; le guard
    # se contente de brancher les deux transports dessus.
    matrix_source = _source("utils/access_matrix.py")
    assert "is_bot_manager" not in checks_source
    assert "has_manager_permission" not in checks_source
    assert "is_bot_manager" not in guard_source
    assert "has_manager_permission" not in guard_source
    assert "is_bot_manager" not in matrix_source
    assert "has_manager_permission" not in matrix_source
    assert "Administrateur" in matrix_source


def test_permission_metadata_is_shared_with_help():
    checks_source = _source("utils/checks.py")
    help_source = _source("cogs/help.py")
    utility_source = _source("utils/command_permissions.py")
    assert "_sentrix_permission_label" in checks_source
    assert "command_requirement" in help_source
    assert "COMMAND_PERMISSION_FALLBACKS" in utility_source


def test_member_data_tables_remain_persistent_by_guild_and_user():
    db_source = _source("database/db.py")
    for table in ("economy", "levels", "message_counts"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in db_source
    assert "PRIMARY KEY (guild_id, user_id)" in db_source


def test_new_python_files_parse():
    for path in (
        "cogs/setup_control_center.py",
        "cogs/help.py",
        "cogs/permission_guard.py",
        "utils/checks.py",
        "utils/command_permissions.py",
        "cogs/__init__.py",
    ):
        ast.parse(_source(path), filename=path)
