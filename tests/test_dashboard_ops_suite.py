from __future__ import annotations

import asyncio
from pathlib import Path

from web import dashboard_ops_suite as ops
from web import dashboard_ops_suite_fix as ops_fix


def test_ops_suite_exposes_expected_ui_contract():
    assert 'id="sentrix-ops-suite-css"' in ops.OPS_CSS
    assert 'id="sentrix-ops-suite-js"' in ops.OPS_JS
    for label in (
        "Diagnostic automatique",
        "Historique et rollback",
        "Mode maintenance",
        "Commandes par salon",
        "Import / export / duplication",
        "Activité staff",
        "Onboarding",
    ):
        assert label in ops.OPS_JS
    assert "/ops/overview" in ops.OPS_JS
    assert "/ops/history/" in ops.OPS_JS
    assert "/ops/repair" in ops.OPS_JS
    assert "/ops/maintenance" in ops.OPS_JS
    assert "/ops/policies" in ops.OPS_JS


def test_safe_clone_patch_is_present():
    assert 'id="sentrix-ops-suite-fix-js"' in ops_fix.PATCH_JS
    assert "/ops/clone-safe/" in ops_fix.PATCH_JS


def test_ha_bootstrap_installs_ops_before_aiohttp():
    source = Path("railway_ha_product_boot.py").read_text(encoding="utf-8")
    ops_pos = source.index("dashboard_ops_suite as _dashboard_ops_suite")
    fix_pos = source.index("dashboard_ops_suite_fix as _dashboard_ops_suite_fix")
    ha_pos = source.index("import railway_ha_boot as ha_boot")
    assert ops_pos < fix_pos < ha_pos


class _Row(dict):
    pass


class _FakeDb:
    async def get_guild_config(self, guild_id):
        return _Row({
            "guild_id": guild_id,
            "prefix": "+",
            "welcome_channel": 123,
            "updated_at": 999,
        })

    async def get_automod(self, guild_id):
        return _Row({"guild_id": guild_id, "antispam": 1, "updated_at": 999})

    async def fetchone(self, query, params):
        return _Row({"guild_id": params[0], "enabled": 1, "daily_limit": 50, "updated_at": 999})


class _FakeDashboard:
    TEXT_FIELDS = {"prefix": (1, 5)}
    URL_FIELDS = set()
    ROLE_FIELDS = set()
    CHANNEL_FIELDS = {"welcome_channel"}
    BOOL_FIELDS = set()
    INT_FIELDS = {}
    AUTOMOD_FIELDS = {"antispam"}
    AI_BOOL_FIELDS = {"enabled"}
    AI_INT_FIELDS = {"daily_limit": (1, 10000)}
    AI_CHOICE_FIELDS = {}


def test_clean_snapshot_filters_internal_database_columns():
    # install() replaces ops._snapshot with the clean compatibility implementation.
    dashboard = _FakeDashboard()
    dashboard.INDEX_HTML = "<html><head></head><body></body></html>"
    dashboard.build_app = lambda bot: None
    dashboard.handle_update_guild = lambda request: None
    ops_fix._INSTALLED = False
    assert ops_fix.install(dashboard, ops) is True
    snapshot = asyncio.run(ops._snapshot(dashboard, _FakeDb(), 42))
    assert snapshot["settings"] == {"prefix": "+", "welcome_channel": 123}
    assert snapshot["automod"] == {"antispam": 1}
    assert snapshot["ai"] == {"enabled": 1, "daily_limit": 50}
    assert "guild_id" not in snapshot["settings"]
    assert "updated_at" not in snapshot["ai"]
