from pathlib import Path


def test_v9_targets_the_real_unified_v2_dom():
    source = Path("web/dashboard_unified_adapter_v9.py").read_text(encoding="utf-8")
    assert 'id="sentrix-unified-adapter-v9-css"' in source
    assert 'id="sentrix-unified-adapter-v9-js"' in source
    assert '$("content")' in source
    assert 'document.querySelector(".workspace")' in source
    assert 'serverContent' not in source


def test_v9_exposes_visible_real_discord_verification():
    source = Path("web/dashboard_unified_adapter_v9.py").read_text(encoding="utf-8")
    assert "Vérification Discord réelle" in source
    assert "CAPTCHA V96 RÉEL" in source
    assert "Publier sur Discord" in source
    assert "/verification-v6/publish" in source
    assert 'action:"verification_save"' in source
    assert 'captcha_enabled:captcha' in source
    assert 'channel_id:channel' in source
    assert 'role_id:role' in source


def test_v9_varies_real_unified_pages():
    source = Path("web/dashboard_unified_adapter_v9.py").read_text(encoding="utf-8")
    for tab in (
        "logs",
        "security",
        "moderation",
        "tickets",
        "ai",
        "notifications",
        "verification",
        "roles",
        "economy",
        "levels",
        "diagnostic",
    ):
        assert f'body[data-sx-tab="{tab}"]' in source


def test_finalizer_requires_v9_after_legacy_freeze():
    source = Path("sentrix_dashboard_finalizer_v7.py").read_text(encoding="utf-8")
    assert "from web import dashboard_unified_adapter_v9" in source
    assert "dashboard_unified_adapter_v9.install(dashboard)" in source
    assert "sentrix-unified-adapter-v9-css" in source
    assert "sentrix-unified-adapter-v9-js" in source
    assert "real_verify=%s" in source
