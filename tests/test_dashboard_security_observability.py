from __future__ import annotations

import inspect
from pathlib import Path

from web import dashboard_api_security


ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "web" / "dashboard_ui" / "js" / "30_modules.js").read_text(encoding="utf-8")


def test_security_dashboard_api_registers_observability_routes():
    source = inspect.getsource(dashboard_api_security.register)
    assert '"/api/guilds/{guild_id}/security/overview"' in source
    assert '"/api/guilds/{guild_id}/security/simulate"' in source
    assert '"/api/guilds/{guild_id}/security/panic"' in source


def test_security_dashboard_panics_only_with_snapshot_and_owner_guard():
    source = inspect.getsource(dashboard_api_security.register)
    assert "_is_critical_owner" in source
    assert "panic_snapshots" in source
    assert "_panic_locks" in source
    assert "_lock_text_channel" in source
    assert "panic_restore_partial" in source


def test_security_dashboard_has_visible_risk_timeline_and_dry_run():
    for marker in (
        "Posture de sécurité",
        "Réponse d’urgence",
        "Simulation / dry-run",
        "Timeline sécurité",
        "Risque",
        "Protection",
        "Activer PANIC",
        "Restaurer le serveur",
        "/security/overview",
        "/security/panic",
    ):
        assert marker in UI


def test_security_dashboard_does_not_poll_or_mutate_dom_periodically():
    security_start = UI.index("const securityOverview")
    security_end = UI.index("async function renderVerification", security_start)
    section = UI[security_start:security_end]
    assert "setInterval(" not in section
    assert "MutationObserver" not in section
    assert "dataset.sxTab" not in section
