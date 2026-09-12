from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _profile_source() -> str:
    return (ROOT / "cogs" / "profile_oxyde_runtime.py").read_text(encoding="utf-8")


def test_profile_runtime_is_loaded_in_production():
    boot = (ROOT / "railway_boot.py").read_text(encoding="utf-8")
    assert 'bot_main.EXTENSIONS.append("cogs.profile_oxyde_runtime")' in boot


def test_profile_runtime_is_a_real_extension():
    source = _profile_source()
    assert "async def setup(bot: commands.Bot)" in source
    assert "install(bot)" in source


def test_me_is_kept_out_of_duplicate_pruning():
    source = _profile_source()
    assert 'duplicates.discard("me")' in source
    assert "bot_main.PRUNED_COMMANDS" in source


def test_me_is_personal_stats_not_profile():
    source = _profile_source()
    start = source.index("async def me_callback")
    end = source.index("def install", start)
    callback = source[start:end]
    assert "cog._send_stats(ctx, ctx.author)" in callback
    assert "CleanProfileView" not in callback
    assert "build_page" not in callback


def test_profile_and_profil_keep_community_profile_surface():
    aliases = (ROOT / "cogs" / "common_command_names.py").read_text(encoding="utf-8")
    source = _profile_source()
    assert '"profile": ("profil",)' in aliases
    assert "CleanProfileView" in source
    assert 'build_page(bot, ctx.guild, member, ctx.author.id, "overview")' in source


def test_profile_overview_is_compact_inline_grid():
    source = _profile_source()
    overview_start = source.index("# Vue principale compacte")
    overview_end = source.index("class CleanProfileView", overview_start)
    overview = source[overview_start:overview_end]

    for section in ("Progression", "Économie", "Activité", "Compte", "Badges"):
        assert f'name="{section}"' in overview

    # La vue principale doit tenir en quelques lignes/colonnes au lieu d'empiler
    # chaque métrique sur deux lignes et chaque section en pleine largeur.
    assert "inline=True" in overview
    assert "inline=False" not in overview
    assert 'f"Niveau **' in overview
    assert 'f"XP **' in overview
    assert 'f"Rang **' in overview
    assert 'f"Portefeuille **' in overview
    assert 'f"Banque **' in overview
    assert 'f"Total **' in overview
    assert 'f"Messages **' in overview
    assert 'f"Vocal **' in overview
    assert 'f"Créé ' in overview
    assert 'f"Arrivé ' in overview
    assert 'value=" · ".join(badges)' in overview


def test_profile_secondary_pages_are_spaced_too():
    source = _profile_source()
    assert '"\\n\\n".join(cleaned)' in source
    assert 'f"Progression\\n**{state}**\\n\\n"' in source
    assert 'f"Palier\\n**{progression[\'tier\']}**\\n\\n"' in source
