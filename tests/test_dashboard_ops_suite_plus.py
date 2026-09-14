from __future__ import annotations

from pathlib import Path

from web import dashboard_ops_suite_plus as plus


def test_plus_ui_exposes_remaining_dashboard_features():
    assert 'id="sentrix-ops-suite-plus-js"' in plus.PLUS_JS
    for label in (
        "Accès dashboard par rôle",
        "Logs filtrables",
        "Prévisualisation avant import",
        "État avancé",
    ):
        assert label in plus.PLUS_JS
    assert "/ops/logs" in plus.PLUS_JS
    assert "/ops/preview" in plus.PLUS_JS
    assert "/ops/health" in plus.PLUS_JS
    assert "/ops/access" in plus.PLUS_JS


def test_access_tier_write_matrix_is_fail_closed():
    assert plus._write_allowed("viewer", "/api/guilds/1/ops/overview", "GET") is True
    assert plus._write_allowed("viewer", "/api/guilds/1/settings", "PUT") is False
    assert plus._write_allowed("operator", "/api/guilds/1/ops/repair", "POST") is True
    assert plus._write_allowed("operator", "/api/guilds/1/sanctions/2/unmute", "POST") is True
    assert plus._write_allowed("operator", "/api/guilds/1/ops/import", "POST") is False
    assert plus._write_allowed("admin", "/api/guilds/1/ops/import", "POST") is True
    assert plus._write_allowed(None, "/api/guilds/1/ops/overview", "GET") is False


def test_plus_is_wired_through_compatibility_layer_before_ha_boot():
    fix_source = Path("web/dashboard_ops_suite_fix.py").read_text(encoding="utf-8")
    boot_source = Path("railway_ha_product_boot.py").read_text(encoding="utf-8")
    assert "dashboard_ops_suite_plus.install(dashboard, ops)" in fix_source
    assert "dashboard_ops_suite_fix.install(dashboard_web, _dashboard_ops_suite)" in boot_source
    assert boot_source.index("dashboard_ops_suite_fix.install") < boot_source.index("import railway_ha_boot as ha_boot")


def test_log_kinds_and_tiers_are_explicit_allowlists():
    assert plus._TIER_RANK == {"viewer": 1, "operator": 2, "admin": 3}
    source = Path("web/dashboard_ops_suite_plus.py").read_text(encoding="utf-8")
    assert '{"commands", "sanctions", "automod", "history"}' in source
    assert "sentrix_dashboard_role_access" in source
