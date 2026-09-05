from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ha_product_boot_installs_dashboard_before_launcher_import():
    source = (ROOT / "railway_ha_product_boot.py").read_text(encoding="utf-8")
    product = source.index("install_dashboard_prestart(dashboard_web)")
    embeds = source.index("_install_embed_dashboard_finish()")
    launcher = source.index("import railway_ha_boot as ha_boot")
    assert product < launcher
    assert embeds < launcher
    assert "raise RuntimeError" in source
    assert "asyncio.run(ha_boot.run())" in source


def test_final_dashboard_is_reapplied_at_build_app_time():
    source = (ROOT / "railway_ha_product_boot.py").read_text(encoding="utf-8")
    assert "_original_build_app = dashboard_web.build_app" in source
    assert "def _build_app_with_final_dashboard(bot):" in source
    assert "if not _install_embed_dashboard_finish():" in source
    assert "app = _original_build_app(bot)" in source
    assert "dashboard_web.build_app = _build_app_with_final_dashboard" in source
    assert "_sentrix_final_dashboard_build_guard = True" in source


def test_existing_ha_launcher_remains_unchanged_entrypoint_logic():
    source = (ROOT / "railway_ha_boot.py").read_text(encoding="utf-8")
    assert "await boot.run()" in source
    assert "await coordinator.close(release=True)" in source
