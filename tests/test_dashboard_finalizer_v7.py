from pathlib import Path


def test_dashboard_finalizer_runs_only_at_v8_build_boundary():
    verification_source = Path("sentrix_verification_v96_finalizer.py").read_text(encoding="utf-8")
    primary_source = Path("railway_ha_product_boot_v8.py").read_text(encoding="utf-8")
    standby_source = Path("sentrix_v98_ha_product_boot_v8.py").read_text(encoding="utf-8")

    # V96 owns verification/slash only. It must not pre-apply the dashboard authority
    # before the legacy V55 freeze, otherwise V7/V18 executes twice during production boot.
    assert "from sentrix_dashboard_finalizer_v7 import install as install_dashboard_v7" not in verification_source
    assert "install_dashboard_v7()" not in verification_source

    # Primary and standby V8 wrappers are the only boot-level owners of V7 and invoke it
    # at the actual build_app boundary, after legacy dashboard layers have finished.
    for source in (primary_source, standby_source):
        assert "from sentrix_dashboard_finalizer_v7 import install as install_dashboard_v7" in source
        assert "dashboard_ok = bool(install_dashboard_v7())" in source
        assert "_install_embed_dashboard_finish" in source


def test_dashboard_finalizer_requires_all_production_ui_markers():
    source = Path("sentrix_dashboard_finalizer_v7.py").read_text(encoding="utf-8")
    for marker in (
        "sentrix-control-center-css",
        "sentrix-control-center-js",
        "sentrix-control-center-v3-js",
        "sentrix-premium-ui-v4-css",
        "sentrix-premium-ui-v4-js",
        "sentrix-section-variants-v5-css",
        "sentrix-section-variants-v5-js",
        "sentrix-dashboard-verification-v6-css",
        "sentrix-dashboard-verification-v6-js",
    ):
        assert marker in source


def test_real_verification_dashboard_uses_existing_v96_contracts():
    source = Path("web/dashboard_verification_v6.py").read_text(encoding="utf-8")
    assert "verification_panels_v96" in source
    assert 'set_guild_config(guild.id, "verify_role", role.id)' in source
    assert 'set_guild_config(guild.id, "verification_role", role.id)' in source
    assert 'set_guild_config(guild.id, "verification_channel", channel.id)' in source
    assert 'set_guild_config(guild.id, "verify_captcha_enabled", 1)' in source
    assert "VerifyView" in source
    assert "/verification-v6/publish" in source
    assert "_require_csrf" in source


def test_verification_dashboard_exposes_real_discord_publish_ui():
    source = Path("web/dashboard_verification_v6.py").read_text(encoding="utf-8")
    assert "Vérification Discord réelle" in source
    assert "Publier sur Discord" in source
    assert "CAPTCHA réel" in source
    assert "Mettre à jour sur Discord" in source
