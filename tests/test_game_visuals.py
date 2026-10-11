"""Gameplay GIF regressions: visual-only changes, Components V2 remain interactive."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from utils import game_visuals, sentrix_panels as panels

ROOT = Path(__file__).resolve().parents[1]


def test_curated_media_are_real_direct_animated_gif_links():
    assert len(game_visuals.GIFS) >= 7
    assert len(set(game_visuals.GIFS.values())) == len(game_visuals.GIFS)
    assert all(
        url.startswith("https://media1.tenor.com/m/") and url.endswith(".gif")
        for url in game_visuals.GIFS.values()
    )


def test_each_game_family_chooses_relevant_anime_scene():
    cases = {
        "Duel": "fight",
        "Zombie": "fight",
        "Course à l'emoji": "race",
        "Quiz de culture": "think",
        "Memory": "think",
        "Pile ou face": "coin",
        "Coinflip": "coin",
        "SLAP": "slap",
        "Bombes": "fight",
        "Puissance 4": "arcade",
    }
    for game, expected in cases.items():
        assert game_visuals.scene_for(game, "La partie commence.") == expected, game


def test_win_loss_and_invalid_input_scenes_are_not_confused():
    assert game_visuals.scene_for("Bombes", "🏆 Vous avez gagné !", "success") == "win"
    assert game_visuals.scene_for("Bombes", "💥 Vous avez perdu.", "danger") == "loss"
    assert game_visuals.scene_for("Quiz", "✅ Bonne réponse, victoire !") == "win"
    assert game_visuals.scene_for("Quiz", "Mauvais choix, vous avez perdu.") == "loss"
    assert game_visuals.scene_for("Quiz", "Ce choix est invalide", "warning") is None
    assert game_visuals.scene_for("Bombes", "Pas assez d'argent", "danger") is None
    assert game_visuals.scene_for("Historique des jeux", "Vous avez gagné", "success") is None
    assert game_visuals.scene_for("Classement", "Voici les gagnants") is None


def test_animation_is_in_same_components_v2_panel_as_content_and_buttons():
    original = discord.Embed(title="🎮 Duel", description="⚔️ Choisissez votre attaque.")
    result = game_visuals.decorate_embed(
        original, title="Duel", description=original.description,
    )
    assert result is original
    assert result.image.url == game_visuals.GIFS["fight"]
    panel = panels.depuis_embed(result)
    content = repr(panel.to_components())
    assert game_visuals.GIFS["fight"] in content
    assert "Choisissez votre attaque" in content
    assert "Duel" in content


def test_invalid_command_does_not_show_a_heavy_gif():
    embed = discord.Embed(title="Minesweeper", description="Permission manquante.")
    game_visuals.decorate_embed(
        embed, title="Minesweeper", description=embed.description,
        kind="warning",
    )
    assert not embed.image.url


def test_game_modules_use_same_single_visual_resolver():
    economy = (ROOT / "cogs/games_economy.py").read_text(encoding="utf-8")
    mini = (ROOT / "cogs/minigames.py").read_text(encoding="utf-8")
    arcade = (ROOT / "cogs/games_arcade.py").read_text(encoding="utf-8")
    for name, source in (("economy", economy), ("mini", mini)):
        assert "game_visuals.decorate_embed(" in source, name
    assert "from cogs.games_economy import _embed" in arcade
    assert 'if "gagne la partie" in status.casefold() else None' in economy
    assert "image_for" in economy
