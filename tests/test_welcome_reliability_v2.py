from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_welcome_text_mode_does_not_require_embed_permission():
    source = (ROOT / "cogs" / "setup_v2_completion.py").read_text(encoding="utf-8")
    assert "require_embed=presentation.get(\"mode\") != \"text\"" in source
    assert "if require_embed and not perms.embed_links" in source


def test_event_cards_fallback_without_attach_files():
    source = (ROOT / "cogs" / "setup_v2_completion.py").read_text(encoding="utf-8")
    assert source.count("if perms is not None and perms.attach_files:") >= 2


def test_goodbye_uses_same_dedup_guard_as_welcome():
    source = (ROOT / "cogs" / "setup_v2_completion.py").read_text(encoding="utf-8")
    assert 'join_dedup.reclamer(bot, member.guild.id, member.id, "goodbye")' in source
    assert 'core.module_enabled(bot, member.guild.id, "goodbye")' in source


def test_deleted_event_channel_is_not_recreated():
    source = (ROOT / "cogs" / "setup_v2_completion.py").read_text(encoding="utf-8")
    assert "guild.create_text_channel" not in source
