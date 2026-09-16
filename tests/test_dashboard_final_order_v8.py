from pathlib import Path


def test_procfile_uses_v8_ha_product_entrypoint():
    source = Path("Procfile").read_text(encoding="utf-8")
    assert "sentrix_v98_ha_product_boot_v8.py" in source
    assert "sentrix_v98_boot.py" not in source


def test_shared_product_boot_finalizes_v25_to_v28_at_build_boundary():
    source = Path("railway_ha_product_boot.py").read_text(encoding="utf-8")
    assert "from sentrix_dashboard_finalizer_v7 import install as install_dashboard_v7" in source
    assert "install_dashboard_v7()" in source
    assert source.index("if not _install_v97_dashboard(dashboard_web):") < source.index("if not install_dashboard_v7():")
    assert source.index("if not install_dashboard_v7():") < source.index("app = _original_build_app(bot)")


def test_primary_v8_finalizes_at_build_boundary():
    source = Path("railway_ha_product_boot_v8.py").read_text(encoding="utf-8")
    assert "product_boot._install_embed_dashboard_finish = _finish_with_dashboard_v8" in source
    assert "install_dashboard_v7()" in source
    assert "actual build_app boundary after legacy V55 freeze" in source


def test_standby_v8_finalizes_at_build_boundary():
    source = Path("sentrix_v98_ha_product_boot_v8.py").read_text(encoding="utf-8")
    assert "product_boot._install_embed_dashboard_finish = _finish_with_dashboard_v8" in source
    assert "install_dashboard_v7()" in source
    assert "actual build_app boundary after legacy V55 freeze" in source
