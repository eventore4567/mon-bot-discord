from __future__ import annotations

from pathlib import Path

from services.dashboard.models import EnvironmentDashboard
from services.dashboard.status_page import ComponentStatus, public_status
from services.promotion.guard import CanaryResult, contains_destructive_migration, decide_promotion


def canary(*, healthy: bool = True, app: str = "canary-app", duration: float = 120) -> CanaryResult:
    return CanaryResult(
        healthy=healthy, started_at=10, observed_until=10 + duration, application_id=app
    )


def test_canary_requires_distinct_discord_application_and_full_bake() -> None:
    assert not decide_promotion(
        prod_application_id="prod", canary=canary(app="prod"), bake_seconds=60
    ).allowed
    assert not decide_promotion(
        prod_application_id="prod", canary=canary(healthy=False), bake_seconds=60
    ).allowed
    assert not decide_promotion(
        prod_application_id="prod", canary=canary(duration=59), bake_seconds=60
    ).allowed
    assert decide_promotion(
        prod_application_id="prod", canary=canary(duration=60), bake_seconds=60
    ).allowed


def test_red_canary_never_promotes() -> None:
    decision = decide_promotion(
        prod_application_id="prod", canary=canary(healthy=False), bake_seconds=0
    )
    assert decision.allowed is False
    assert "unhealthy" in decision.reason


def test_destructive_schema_blocks_without_explicit_human_confirmation() -> None:
    sql = "ALTER TABLE users DROP COLUMN legacy_field;"
    assert contains_destructive_migration(sql)
    blocked = decide_promotion(
        prod_application_id="prod", canary=canary(), bake_seconds=60, migration_sql=sql
    )
    assert not blocked.allowed and blocked.requires_human_confirmation
    allowed = decide_promotion(
        prod_application_id="prod",
        canary=canary(),
        bake_seconds=60,
        migration_sql=sql,
        human_confirmed_destructive=True,
    )
    assert allowed.allowed


def test_schema_guard_ignores_comment_only_examples() -> None:
    assert not contains_destructive_migration("-- DROP COLUMN only documented here\nSELECT 1;")


def test_dashboard_never_overstates_generic_health() -> None:
    managed = EnvironmentDashboard("e1", "managed", "healthy", 900, 1000)
    generic = EnvironmentDashboard("e2", "generic", "healthy", 900, 1000)
    assert "Gateway" in managed.as_dict()["health_level"]
    assert "process/log/REST" in generic.as_dict()["health_level"]
    assert generic.as_dict()["identify_budget"] == {"remaining": 900, "total": 1000}


def test_public_status_and_templates_exist() -> None:
    status = public_status([ComponentStatus("control-plane", "operational")])
    assert status["status"] == "operational"
    root = Path(__file__).parents[2]
    py = (root / "templates/managed/discordpy/main.py").read_text()
    js = (root / "templates/managed/discordjs/index.js").read_text()
    assert "wait_for_gateway_gate" in py
    assert "SENTRIX_DISCORD_TOKEN_FILE" in py
    assert "waitForGatewayGate" in js
    assert "SENTRIX_DISCORD_TOKEN_FILE" in js
