from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_real_primary_boot_installs_canonical_surface_after_v98():
    text = (ROOT / "railway_ha_product_boot.py").read_text(encoding="utf-8")
    v98 = text.index("_install_v98_grouped_slash()")
    canonical = text.index("_install_canonical_surface()")
    assert canonical > v98
    assert "from sentrix_canonical_command_surface import install" in text


def test_real_primary_boot_installs_playlist_semantics_after_music_loader():
    text = (ROOT / "railway_ha_product_boot.py").read_text(encoding="utf-8")
    music = text.index("_install_music_v102()")
    playlist = text.index("_install_playlist_semantics()")
    assert playlist > music
    assert "from sentrix_music_playlist_semantics import install" in text


def test_standby_wrapper_delegates_to_same_product_bootstrap():
    text = (ROOT / "sentrix_v98_ha_product_boot.py").read_text(encoding="utf-8")
    assert "railway_ha_product_boot" in text
