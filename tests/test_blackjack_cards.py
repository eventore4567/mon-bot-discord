"""Rendu réel des cartes Blackjack sans GIF extérieur ni Markdown cassé."""
from __future__ import annotations

import io
import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
from PIL import Image

from cogs.minigames import Minigames
from utils.blackjack_cards import PHASES, render_table_gif


PLAYER = [("A♠", 11), ("9♥", 9)]
DEALER = [("7♦", 7), ("8♣", 8)]


def test_blackjack_cards_are_animated_for_every_game_action():
    """Toutes les actions produisent un vrai GIF avec plusieurs images."""
    for phase in sorted(PHASES):
        data = render_table_gif(PLAYER, DEALER, hidden=phase in {"deal", "hit"}, phase=phase)
        assert data.startswith((b"GIF87a", b"GIF89a")), phase
        assert len(data) < 8_000_000, phase
        with Image.open(io.BytesIO(data)) as image:
            assert image.format == "GIF"
            assert image.n_frames >= 2, phase
            assert image.size == (900, 490)


def test_blackjack_hidden_card_differs_from_revealed_card():
    hidden = render_table_gif(PLAYER, DEALER, hidden=True, phase="deal")
    revealed = render_table_gif(PLAYER, DEALER, hidden=False, phase="stand")
    with Image.open(io.BytesIO(hidden)) as a, Image.open(io.BytesIO(revealed)) as b:
        assert a.convert("RGB").tobytes() != b.convert("RGB").tobytes()


def test_blackjack_panel_attaches_local_cards_not_coinflip_gif():
    embed = discord.Embed(title="Blackjack", description="À vous de jouer")
    panneau = Minigames._panneau_blackjack(
        embed, PLAYER, DEALER, devoile=False, phase="deal",
    )
    components = repr(panneau.to_components())
    assert "attachment://sentrix_blackjack.gif" in components
    assert "sentrix_game_coin.gif" not in components
    files = panneau.fichiers()
    assert len(files) == 1
    assert files[0].filename == "sentrix_blackjack.gif"
    assert files[0].fp.read(6) in (b"GIF87a", b"GIF89a")
    files[0].close()
    another = panneau.fichiers()
    assert another[0].fp is not files[0].fp
    another[0].close()


def test_blackjack_aces_and_valid_deck():
    paquet = Minigames._paquet()
    assert len(paquet) == 52
    assert len({code for code, _ in paquet}) == 52
    assert Minigames._total([("A♠", 11), ("A♥", 11), ("9♣", 9)]) == 21
    assert Minigames._total([("10♣", 10), ("8♥", 8), ("5♠", 5)]) == 23
