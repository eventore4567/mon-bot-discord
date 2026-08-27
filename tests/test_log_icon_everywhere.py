from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSPORT = ROOT / "cogs" / "log_transport_v52.py"


def source() -> str:
    return TRANSPORT.read_text(encoding="utf-8")


def test_source_compiles():
    text = source()
    compile(text, str(TRANSPORT), "exec")


def test_icon_prefers_live_bot_avatar():
    text = source()
    assert 'avatar = getattr(user, "display_avatar", None)' in text
    assert 'url = getattr(avatar, "url", None)' in text
    assert "_SENTRIX_LOG_ICON_FALLBACK" in text


def test_every_render_forces_sentrix_icon():
    text = source()
    assert "def _force_sentrix_log_icon" in text
    assert "embed.set_thumbnail(url=_sentrix_log_icon_url())" in text
    assert "return _force_sentrix_log_icon(rendered)" in text
    # Le chemin normal et le fallback visuel doivent tous les deux passer par la même règle.
    assert text.count("return _force_sentrix_log_icon(rendered)") >= 2


def test_transport_keeps_bot_reference_for_files_and_all_other_routes():
    text = source()
    assert "global _BOT" in text
    assert "_BOT = bot" in text
    assert '"_force_sentrix_log_icon"' in text


if __name__ == "__main__":
    test_source_compiles()
    test_icon_prefers_live_bot_avatar()
    test_every_render_forces_sentrix_icon()
    test_transport_keeps_bot_reference_for_files_and_all_other_routes()
    print("log icon contracts: ok")
