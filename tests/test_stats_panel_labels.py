"""Régression UI : les émojis personnalisés ne doivent pas couper les statistiques.

Avant correction, le marquage <:sentrix_voice:ID> comptait dans la limite de
40 caractères et transformait « Temps vocal » en « Te… » dans le panneau.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from utils import sentrix_emojis, sentrix_panels


def test_libelles_complets_avec_emojis_personnalises():
    sentrix_emojis.reinitialiser()
    try:
        sentrix_emojis.amorcer({
            "sentrix_voice": "<:sentrix_voice:410000000000000001>",
            "sentrix_level": "<:sentrix_level:410000000000000002>",
        })

        embed = discord.Embed(
            title="Profil de tomioka",
            description="Toutes les statistiques de ce membre sur le serveur.",
        )
        embed.add_field(name="💬 Messages", value="0", inline=True)
        embed.add_field(name="🔊 Temps vocal", value="0 min", inline=True)
        embed.add_field(name="⭐ Réputation", value="0 point(s)", inline=True)
        embed.add_field(name="📅 Membre depuis", value="21 septembre 2026", inline=True)

        panneau = sentrix_panels.depuis_embed(embed, compact=True)
        assert panneau.sections_source[0].titre == "Résumé"
        rendu = panneau.sections_source[0].rendu()

        assert "Temps vocal" in rendu
        assert "Réputation" in rendu
        assert "Membre depuis" in rendu
        assert "0 min" in rendu
        assert "0 point(s)" in rendu
        assert "Te…" not in rendu
        assert "Ré…" not in rendu
        assert "<:sentrix_voice:410000000000000001>" in rendu
        assert "<:sentrix_level:410000000000000002>" in rendu
    finally:
        sentrix_emojis.reinitialiser()


def test_libelles_complets_sans_emojis_personnalises():
    sentrix_emojis.reinitialiser()
    embed = discord.Embed(title="Profil de tomioka")
    embed.add_field(name="🔊 Temps vocal", value="12 h", inline=True)
    embed.add_field(name="⭐ Réputation", value="5 points", inline=True)

    panneau = sentrix_panels.depuis_embed(embed, compact=True)
    rendu = panneau.sections_source[0].rendu()

    assert "Temps vocal" in rendu
    assert "Réputation" in rendu
    assert "12 h" in rendu
    assert "5 points" in rendu
