from pathlib import Path


def test_dashboard_finalizer_runs_after_legacy_boot_via_v96_finalizer():
    source = Path("sentrix_verification_v96_finalizer.py").read_text(encoding="utf-8")
    assert "from sentrix_dashboard_finalizer_v7 import install as install_dashboard_v7" in source
    assert "install_dashboard_v7()" in source


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
