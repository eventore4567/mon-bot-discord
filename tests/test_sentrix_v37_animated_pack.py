from __future__ import annotations

from pathlib import Path

from cogs import sentrix_emoji_markup_guard_v361 as guard
from cogs import sentrix_emoji_runtime as ui


ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "sentrix_emojis"


def test_v37_pack_has_ten_unique_compact_gifs() -> None:
    assert len(ui.PACK) == 10
    names = [name for name, _filename in ui.PACK.values()]
    assert len(set(names)) == 10
    assert all(name.startswith("sxv37_") for name in names)

    for _key, (_name, filename) in ui.PACK.items():
        path = ASSET_DIR / filename
        data = path.read_bytes()
        assert data[:6] in {b"GIF87a", b"GIF89a"}
        assert len(data) < 64 * 1024
        # NETSCAPE2.0 = GIF animé en boucle, pas une image PNG renommée.
        assert b"NETSCAPE2.0" in data


def test_only_old_sentrix_pack_is_marked_for_deletion() -> None:
    assert ui._is_legacy_pack_emoji_name("sxv36_loading") is True
    assert ui._is_legacy_pack_emoji_name("sxv36_staff") is True
    assert ui._is_legacy_pack_emoji_name("sxv37_loading") is False
    assert ui._is_legacy_pack_emoji_name("mon_emoji") is False


def test_real_custom_emoji_tokens_are_never_broken() -> None:
    token = "<a:sxv37_loading:1541658913592713327>"
    assert guard._repair_broken(f"{token} Chargement") == f"{token} Chargement"
    assert ui._clean_artifacts(f"{token} Chargement") == f"{token} Chargement"


def test_broken_old_and_new_fragments_are_cleaned() -> None:
    assert guard._repair_broken("a:sxv36_update:1541658913592713327> Configuration") == "Configuration"
    assert guard._repair_broken("a:sxv37_update:1541658913592713327> Configuration") == "Configuration"
    assert guard._repair_broken("a a a Centre de contrôle") == "Centre de contrôle"


def test_state_mapping_uses_compact_pack_keys() -> None:
    assert ui._animated_state_key("Terminé", kind="success") == "ok"
    assert ui._animated_state_key("Erreur", kind="danger") == "error"
    assert ui._animated_state_key("Attention", kind="warning") == "alert"
    assert ui._animated_state_key("Chargement", kind="info") == "loading"
    assert ui._animated_state_key("Bot en ligne", kind="info") == "online"
    assert ui._animated_state_key("Accès interdit", kind="info") == "no"
