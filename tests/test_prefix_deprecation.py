"""Avis de retrait des commandes « + » (28/10/2026 : SentriX passe à 100 % « / »)."""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
from discord.ext import commands

from cogs import prefix_deprecation as avis


def _bot() -> commands.Bot:
    bot = commands.Bot(command_prefix="+", intents=discord.Intents.none())

    @bot.command(name="clear")
    async def clear(ctx):
        pass

    @bot.tree.command(name="clear", description="x")
    async def clear_slash(interaction):
        pass

    @bot.command(name="vieux")
    async def vieux(ctx):
        pass

    return bot


def test_avis_donne_la_date_le_temps_restant_et_la_commande_slash():
    bot = _bot()
    texte = avis.texte_avis(bot, bot.get_command("clear"))
    assert "30 novembre 2026" in texte
    assert f"<t:{int(avis.DATE_RETRAIT.timestamp())}:R>" in texte
    assert "/clear" in texte


def test_sans_equivalent_slash_l_avis_reste_general():
    bot = _bot()
    assert "Utilisez les commandes `/`." in avis.texte_avis(bot, bot.get_command("vieux"))


def test_une_seule_fois_par_jour_et_par_personne():
    avis._dernier_avis.clear()
    t = 1_790_000_000.0
    assert avis.doit_avertir(1, 2, t) is True
    assert avis.doit_avertir(1, 2, t + 3600) is False
    assert avis.doit_avertir(1, 3, t + 3600) is True
    assert avis.doit_avertir(1, 2, t + avis.INTERVALLE_S + 1) is True
