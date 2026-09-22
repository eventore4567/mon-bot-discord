from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _profile_source() -> str:
    return (ROOT / "cogs" / "profile_oxyde_runtime.py").read_text(encoding="utf-8")


def test_profile_runtime_is_not_loaded_in_production():
    boot = (ROOT / "railway_boot.py").read_text(encoding="utf-8")
    assert 'bot_main.EXTENSIONS.append("cogs.profile_oxyde_runtime")' not in boot


def test_plus_me_is_removed():
    levels = (ROOT / "cogs" / "levels.py").read_text(encoding="utf-8")
    assert '@commands.hybrid_command(name="me"' not in levels
    assert "async def _legacy_me(" in levels


def test_profile_and_me_are_absent_from_direct_slash_surface():
    surface = (ROOT / "sentrix_command_surface_v110.py").read_text(encoding="utf-8")
    assert '"profile": "me"' not in surface
    assert '"profile": "profile"' not in surface


def test_profilecard_is_the_documented_public_profile():
    aliases = (ROOT / "cogs" / "common_command_names.py").read_text(encoding="utf-8")
    boot = (ROOT / "railway_boot.py").read_text(encoding="utf-8")
    assert '"profilecard": "carte"' in aliases
    assert "/outils profilecard" in boot


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



def test_profilecard_has_plus_command_and_french_alias():
    source = (ROOT / "cogs" / "sentrix_v2.py").read_text(encoding="utf-8")
    assert '@commands.hybrid_command(name="profilecard", aliases=["profilcard"]' in source
    assert "with_app_command=False" in source
    aliases = (ROOT / "cogs" / "common_command_names.py").read_text(encoding="utf-8")
    assert '"profilecard": "carte"' in aliases
