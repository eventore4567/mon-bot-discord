from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "services" / "api" / "static"
MAIN = ROOT / "services" / "api" / "main.py"
INFRA = ROOT / "services" / "api" / "routers" / "infra_status.py"
MIGRATION = ROOT / "migrations" / "0022_worker_capacity_status.sql"


def test_motion_and_health_assets_are_wired() -> None:
    main = MAIN.read_text(encoding="utf-8")
    assert "enhancements.css" in main
    assert "landing-enhancements.js" in main
    assert "dashboard-enhancements.js" in main
    assert (STATIC / "enhancements.css").stat().st_size > 1000
    assert "/healthz" in (STATIC / "landing-enhancements.js").read_text(encoding="utf-8")


def test_dashboard_exposes_real_hosting_readiness_not_fake_online_copy() -> None:
    dashboard = (STATIC / "dashboard-enhancements.js").read_text(encoding="utf-8")
    assert "/v1/infra/status" in dashboard
    assert "AUCUN WORKER" in dashboard
    assert "VPS/serveur" in dashboard


def test_worker_status_preserves_private_node_table() -> None:
    infra = INFRA.read_text(encoding="utf-8")
    migration = MIGRATION.read_text(encoding="utf-8")
    assert "SELECT id FROM nodes" not in infra
    assert "sentrix_configured_worker_count" in infra
    assert "SECURITY DEFINER" in migration
    assert "GRANT EXECUTE" in migration
    assert "SELECT count(*)" in migration
