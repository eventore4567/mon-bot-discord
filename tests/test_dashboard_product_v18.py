from web import dashboard_product_v18


def test_v18_scope_normalisation_is_allowlisted():
    scopes = dashboard_product_v18._normalise_scopes([
        "view",
        "members",
        "dangerous",
        "unknown",
        "view",
    ])
    assert scopes == ["dangerous", "members", "view"]
    assert "unknown" not in scopes


def test_v18_diff_is_stable_and_reports_nested_changes():
    before = {
        "settings": {"prefix": "+", "log_channel": 1},
        "automod": {"antispam": 0},
    }
    after = {
        "settings": {"prefix": "!", "log_channel": 1},
        "automod": {"antispam": 1},
    }
    diff = dashboard_product_v18._diff(before, after)
    paths = {item["path"] for item in diff}
    assert paths == {"automod.antispam", "settings.prefix"}


def test_v18_declares_real_product_scopes_and_runtime_entrypoint():
    assert {"view", "configuration", "members", "automations", "audit", "templates", "dangerous", "admin"} <= dashboard_product_v18.SCOPES
    assert callable(dashboard_product_v18.install)
    assert callable(dashboard_product_v18.install_runtime)
