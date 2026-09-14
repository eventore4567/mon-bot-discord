from pathlib import Path


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
