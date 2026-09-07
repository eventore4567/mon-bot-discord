from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUTH = ROOT / "services" / "api" / "routers" / "auth_routes.py"
MIGRATION = ROOT / "migrations" / "0023_user_org_directory.sql"


def test_org_list_does_not_query_rls_tables_without_tenant_context() -> None:
    text = AUTH.read_text(encoding="utf-8")
    start = text.index("async def list_organizations")
    end = text.index("@router.post(\n    \"/organizations\"", start)
    function = text[start:end]
    assert "sentrix_list_user_organizations" in function
    assert "JOIN org_members" not in function
    assert "FROM organizations" not in function


def test_user_org_directory_is_not_directly_readable_by_app_role() -> None:
    text = MIGRATION.read_text(encoding="utf-8")
    assert "REVOKE ALL ON user_org_directory FROM sentrix_app" in text
    assert "SECURITY DEFINER" in text
    grant = (
        "GRANT EXECUTE ON FUNCTION "
        "public.sentrix_list_user_organizations(uuid) TO sentrix_app"
    )
    assert grant in text


def test_directory_is_synced_from_tenant_scoped_membership_changes() -> None:
    text = MIGRATION.read_text(encoding="utf-8")
    assert "org_members_sync_user_org_directory" in text
    assert "organizations_sync_user_org_directory" in text
    assert "AFTER INSERT OR UPDATE OR DELETE ON org_members" in text
