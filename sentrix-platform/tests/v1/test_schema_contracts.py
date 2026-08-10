from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[2]


def migration(name: str) -> str:
    return (ROOT / "migrations" / name).read_text()


def test_p2_tables_are_rls_and_release_is_immutable_for_app_role() -> None:
    sql = migration("0010_build_chain.sql")
    for table in ("webhook_deliveries", "builds", "releases"):
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in sql
    assert "REVOKE UPDATE, DELETE ON releases FROM sentrix_app" in sql
    assert "FOREIGN KEY (environment_id, org_id)" in sql


def test_p3_release_after_identify_is_structurally_forbidden() -> None:
    sql = migration("0011_identify_broker.sql")
    assert "state = 'released' AND identify_sent_at IS NULL" in sql
    assert "failed_after_identify" in sql
    assert "FOREIGN KEY (discord_application_id, org_id)" in sql


def test_p4_fencing_and_attempt_tables_exist() -> None:
    sql = migration("0012_orchestrator.sql")
    assert "fencing_token" in sql
    assert "deployment_leases" in sql
    assert "deployment_attempts" in sql
    assert "deployment_effects" in sql


def test_p5_database_has_no_plaintext_secret_column() -> None:
    sql = migration("0013_secrets_observability.sql")
    assert "ciphertext bytea" in sql and "wrapped_dek bytea" in sql
    assert "plaintext" not in sql.lower()
    assert "usage_samples" in sql


def test_p6_database_blocks_unconfirmed_destructive_promotion() -> None:
    sql = migration("0014_canary_dashboard.sql")
    assert "no_unconfirmed_destructive_promotion" in sql
    assert "prod_environment_id <> canary_environment_id" in sql
