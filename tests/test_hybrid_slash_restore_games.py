from pathlib import Path

SOURCE = Path("cogs/command_hybrid_slash_restore_v3.py").read_text(encoding="utf-8")


def test_hybrid_restore_ne_recree_pas_les_jeux_en_racines_slash():
    assert "GAME_COMMANDS, NORMAL_DIRECT_COMMANDS" in SOURCE
    assert "if direct_name in GAME_COMMANDS:" in SOURCE
    assert "Les mini-jeux ont déjà leur surface canonique sous /game" in SOURCE
