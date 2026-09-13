import pytest

from sentrix_ops_v111 import HealthFinding, build_simulation, compute_health_score, health_label


def finding(severity: str) -> HealthFinding:
    return HealthFinding(
        code=f"test.{severity}",
        severity=severity,
        title="Test",
        detail="Detail",
        remediation="Fix",
    )


def test_health_score_is_deterministic_and_clamped():
    assert compute_health_score([]) == 100
    assert compute_health_score([finding("low")]) == 95
    assert compute_health_score([finding("critical"), finding("high"), finding("medium")]) == 42
    assert compute_health_score([finding("critical")] * 10) == 0


def test_health_labels_match_thresholds():
    assert health_label(100) == "Excellent"
    assert health_label(90) == "Excellent"
    assert health_label(89) == "Bon"
    assert health_label(75) == "Bon"
    assert health_label(74) == "À renforcer"
    assert health_label(50) == "À renforcer"
    assert health_label(49) == "Fragile"


@pytest.mark.parametrize("kind", ["sanction", "join", "verification", "ticket", "log", "raid"])
def test_simulation_is_always_dry_run(kind):
    plan = build_simulation(kind, target="123")
    assert plan["kind"] == kind
    assert plan["target"] == "123"
    assert plan["dry_run"] is True
    assert plan["steps"]


def test_simulation_rejects_unknown_scenario():
    with pytest.raises(ValueError):
        build_simulation("wipe-real-server")
