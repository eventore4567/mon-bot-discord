from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_member_commands_remain_public_while_admin_commands_fail_closed():
    access = source("utils/control_center_v20_access.py")
    assert "if name in bot_main.PUBLIC_COMMANDS" in access
    assert "return True" in access
    assert "Cette commande n'a pas encore de niveau public validé" in access
    assert "Administrateur" in access


def test_limited_staff_uses_exact_discord_permission_not_generic_mod_role():
    access = source("utils/control_center_v20_access.py")
    exact_block = access.split("required = bot_main.DISCORD_PERMISSION_COMMANDS.get(name)", 1)[1]
    exact_block = exact_block.split("for category, names", 1)[0]
    assert "member.guild_permissions" in exact_block
    assert "getattr(member.guild_permissions, required, False)" in exact_block
    assert "is_mod_or_permission" not in access
    assert "mod_role" not in access


def test_server_admin_and_server_owner_can_open_setup_but_not_grant_global_manager():
    access = source("utils/control_center_v20_access.py")
    facade = source("cogs/control_center_v20.py")
    assert "member.id == guild.owner_id or member.guild_permissions.administrator" in access
    manager_section = facade.split('name="sentrix-manager-list"', 1)[1]
    assert manager_section.count("@checks.is_bot_owner()") >= 3
    assert "global_bot_managers" in manager_section


def test_global_owner_is_recognized_separately_from_guild_permissions():
    access = source("utils/control_center_v20_access.py")
    assert "PRIMARY_CREATOR_ID" in access
    assert "config.OWNER_IDS" in access
    assert "is_bot_creator" in access
    assert "Propriétaire global SentriX" in access


def test_fresh_and_configured_server_paths_are_both_handled():
    state = source("utils/control_center_v20_state.py")
    assert "if row is None" in state
    assert "if not panels" in state
    assert "if not rows" in state
    assert "STATE_UNCONFIGURED" in state
    assert "get_guild_config(guild.id)" in state


def test_deleted_channels_and_roles_are_configuration_errors_not_crashes():
    meta = source("utils/control_center_v20_meta.py")
    state = source("utils/control_center_v20_state.py")
    assert "resource is None" in meta
    assert 'return STATE_ERROR, "Ressource supprimée ou introuvable"' in meta
    assert "guild.get_channel(int(channel_id)) is None" in state
    assert "guild.get_role(int(role_id)) is None" in state
    assert "ERREUR DE CONFIGURATION" in meta


def test_bot_permissions_are_checked_and_displayed():
    meta = source("utils/control_center_v20_meta.py")
    state = source("utils/control_center_v20_state.py")
    assert "_bot_missing_permissions" in meta
    assert "guild.me" in meta
    assert 'name="Permissions SentriX"' in state
    assert "MANQUANT" in state
    assert "OK" in state


def test_v20_does_not_delete_progression_on_membership_events():
    combined = "\n".join(
        source(path)
        for path in (
            "cogs/control_center_v20.py",
            "cogs/control_center_setup_v20.py",
            "cogs/control_center_setup_components_v20.py",
            "utils/control_center_v20_state.py",
            "utils/control_center_v20_access.py",
        )
    ).casefold()
    protected_tables = ("levels", "economy", "message", "bank")
    for table in protected_tables:
        assert f"delete from {table}" not in combined
    assert "on_member_remove" not in combined
    assert "on_member_ban" not in combined


def test_setup_modifications_reuse_existing_tables_instead_of_reinitializing_them():
    setup = source("cogs/control_center_setup_v20.py")
    state = source("utils/control_center_v20_state.py")
    assert "set_guild_config" in setup
    assert "UPDATE ticket_types" in setup
    assert "log_service.set_log_channel" in setup
    assert "social_notifications" in state
    assert "DROP TABLE" not in setup.upper()
    assert "DELETE FROM guild_config" not in setup


def test_permission_failures_have_a_reason_instead_of_silent_return():
    access = source("utils/control_center_v20_access.py")
    assert "raise checks.BotPermissionError" in access
    assert "Permission requise" in access
    facade = source("cogs/control_center_v20.py")
    assert 'raise checks.BotPermissionError(\n                "Permission requise : **Administrateur**."' in facade
