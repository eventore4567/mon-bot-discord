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



def test_ha_configuration_changes_trigger_durable_snapshots():
    db_source = (ROOT / "database" / "db.py").read_text(encoding="utf-8")
    ha_source = (ROOT / "railway_ha_boot.py").read_text(encoding="utf-8")
    config_source = (ROOT / "config.py").read_text(encoding="utf-8")

    assert "_CONFIG_PERSISTENCE_MARKERS" in db_source
    assert "def _is_configuration_write" in db_source
    assert "def set_config_snapshot_callback" in db_source
    assert 'reason="config_change"' in db_source
    assert "_schedule_config_snapshot()" in db_source
    assert "set_config_snapshot_callback(durable.snapshot, delay=0.8)" in ha_source
    assert "RAILWAY_VOLUME_MOUNT_PATH" in config_source
    assert 'os.path.join(_volume_mount, "bot.db")' in config_source


def test_configuration_snapshot_marker_covers_core_setup_tables():
    source = (ROOT / "database" / "db.py").read_text(encoding="utf-8")
    for table in (
        "guild_config",
        "module_settings",
        "automod_settings",
        "log_config",
        "welcome_presentation_v2",
        "command_blocked_channels",
        "command_channel_blocks",
        "automatic_verification_v4",
        "honeypot_verification",
    ):
        assert f'"{table}"' in source
