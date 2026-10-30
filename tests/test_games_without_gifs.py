"""Mini-jeux sans GIF et commandes Fun avec une description utile."""
from pathlib import Path
import ast

GAMES = Path("cogs/games_economy.py").read_text("utf-8")
FUN = Path("cogs/fun_social.py").read_text("utf-8")


def test_game_panels_no_longer_fetch_gifs_or_remote_images():
    ast.parse(GAMES)
    assert "game_visuals" not in GAMES
    assert "sentrix-game-gifs" not in GAMES
    assert "verified_image_for(" not in GAMES
    assert "_victory_gif" not in GAMES
    embed_body = GAMES.split("async def _embed(", 1)[1].split("\n\n#", 1)[0]
    assert "return embed" in embed_body
    assert "decorate_embed_checked" not in embed_body


def test_connect_four_and_boss_still_have_interactive_controls():
    assert "class ConnectFourView(discord.ui.View):" in GAMES
    assert "class _BossFightView(discord.ui.View):" in GAMES
    assert "self.add_item(_ConnectFourButton(col))" in GAMES
    assert "self.add_item(_BossFightButton(label, emoji, action, style))" in GAMES


def test_fun_commands_have_help_text_for_command_registry():
    ast.parse(FUN)
    for name in (
        "cuddle", "highfive", "poke", "tickle", "wave", "dance",
        "aura", "hack", "scan", "ship", "hug", "kiss", "pat",
        "slap", "roast", "compliment",
    ):
        assert f'@commands.command(name="{name}", help="' in FUN
