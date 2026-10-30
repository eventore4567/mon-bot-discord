"""Le contrôle de permissions natif ne doit pas désactiver /presentation."""
from tools import permission_audit_sweep as sweep


def test_presentation_is_not_skipped_from_permission_audit():
    assert "presentation" not in sweep.SKIP_COMMANDS
    assert "embed import" in sweep.SKIP_COMMANDS
