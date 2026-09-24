from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_bare_mention_has_one_short_authority():
    common = _read("cogs/common_command_names.py")
    v5 = _read("cogs/bot_experience_v5.py")

    assert "async def _mention_help(" not in common
    assert "Besoin d'aide ?" not in common
    assert "Ping direct unifié" in common
    assert 'Je suis là. Dis-moi simplement ce que tu veux faire.' in v5


def test_quick_intents_never_invent_category_commands():
    source = _read("cogs/bot_experience_v6.py")
    assert "help_queries" not in source
    assert 'await invoke(reply_to, f"{prefix}help")' in source


def test_help_shortcuts_are_runtime_verified():
    source = _read("cogs/help_clean_style.py")
    assert 'candidates = ["profilecard", "ticket", "daily"]' in source
    assert "bot.get_command(name)" in source
    assert "bot.get_command(display) is not command" in source
    assert 'f"`{prefix}profile`"' not in source


def test_dashboard_share_link_is_the_public_sentrix_link():
    config = _read("config.py")
    arrival = _read("cogs/guild_arrival.py")
    access = _read("cogs/dashboard_access.py")
    help_source = _read("cogs/help.py")
    ai = _read("cogs/ai.py")

    expected = "https://sentrix-standby-production.up.railway.app/app"
    assert expected in config
    for source in (arrival, access, help_source, ai):
        assert "DASHBOARD_SHARE_URL" in source


def test_onboarding_dm_is_compact_embed_not_plain_link_dump():
    source = _read("cogs/guild_arrival.py")
    assert 'title="SentriX est prêt"' in source
    assert 'label="Ouvrir le Dashboard"' in source
    assert '"Dashboard : {dashboard}"' not in source


def test_ai_help_only_lists_registered_prefix_commands():
    source = _read("cogs/ai.py")
    start = source.index("    async def _ai_help(")
    end = source.index("\n    @commands.hybrid_command(name=\"chat\"", start)
    block = source[start:end]
    assert "self.bot.get_command(command_name) is not None" in block
    assert "+chat <message>" not in block
    assert "catalogue complet et à jour" in block


def test_ai_is_told_not_to_hallucinate_removed_commands():
    source = _read("utils/ai_service.py")
    assert "N'invente jamais de commande SentriX" in source
    for stale in ("+configurer", "+profile", "+profil", "+chat", "+me", "+rank"):
        assert stale in source
