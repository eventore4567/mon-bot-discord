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


def test_p4_rollback_waits_for_restored_generation_health() -> None:
    sql = migration("0021_verified_rollback_health.sql")
    assert "step = 'rollback_health'" in sql
    assert "'rollback requested; waiting for healthy restored generation'" in sql
    assert "v_status.generation = v_dep.target_generation" in sql
    assert "SET status = 'rolled_back'" in sql
    rollback_branch = sql.split("IF v_dep.step = 'rollback_health' THEN", 1)[1]
    healthy_branch = rollback_branch.split("IF v_status.instance_id IS NOT NULL", 1)[1]
    assert "v_status.health = 'healthy'" in healthy_branch
    assert healthy_branch.index("v_status.health = 'healthy'") < healthy_branch.index(
        "SET status = 'rolled_back'"
    )


def test_p5_database_has_no_plaintext_secret_column() -> None:
    sql = migration("0013_secrets_observability.sql")
    assert "ciphertext bytea" in sql and "wrapped_dek bytea" in sql
    assert "plaintext" not in sql.lower()
    assert "usage_samples" in sql


def test_p6_database_blocks_unconfirmed_destructive_promotion() -> None:
    sql = migration("0014_canary_dashboard.sql")
    assert "no_unconfirmed_destructive_promotion" in sql
    assert "prod_environment_id <> canary_environment_id" in sql


def test_hosting_workers_use_private_machine_tokens_and_security_definer() -> None:
    sql = migration("0015_hosting_workers.sql")
    assert "CREATE TABLE control_workers" in sql
    assert "token_sha256 bytea" in sql
    assert "REVOKE ALL ON control_workers FROM sentrix_app" in sql
    assert "SECURITY DEFINER" in sql
    assert "sentrix_builder_claim" in sql
    assert "sentrix_orchestrator_tick" in sql


def test_global_workers_route_through_private_control_queues_before_rls() -> None:
    sql = migration("0017_control_queues.sql")
    assert "CREATE TABLE build_control_queue" in sql
    assert "CREATE TABLE deployment_control_queue" in sql
    assert "REVOKE ALL ON build_control_queue, deployment_control_queue FROM sentrix_app" in sql
    assert "set_config('app.current_org', v_org_id::text, true)" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "p_worker_id::text" in sql


def test_github_routing_mirror_contains_no_secret_and_is_not_public() -> None:
    sql = migration("0018_github_control_targets.sql")
    assert "github_control_repositories" in sql
    assert "github_control_targets" in sql
    assert "github_control_repository_unique" in sql
    assert "REVOKE ALL ON github_control_repositories, github_control_targets" in sql
    assert "secret" not in sql.lower()
