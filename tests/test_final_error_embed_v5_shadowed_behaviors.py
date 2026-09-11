"""docs/core-v2-audit-technical-debt.md §3 : cogs/bot_excellence_runtime.py::
improved_error_handler patchait cls.on_command_error (niveau CLASSE), mais
cogs/final_error_embed_v5.py::install() fait un remplacement dur au niveau
INSTANCE (bot.on_command_error = MethodType(prefix_error, bot)), chargé en
dernier dans la chaîne — ce qui masquait définitivement deux comportements
sans lever d'erreur ni le signaler :

1. RuntimeRateLimitError (une CheckFailure sans .message) retombait dans le
   cas générique "Accès refusé" / "Vous n'êtes pas autorisé à utiliser cette
   commande" — un message FAUX pour un simple ralentissement anti-abus.
2. +tictactoe sans argument affichait "Argument manquant" au lieu de
   déclencher le matchmaking automatique d'adversaire.

Les deux comportements ont été rapatriés directement dans
final_error_embed_v5.py (le vainqueur réel de la chaîne) plutôt que de
rétablir un chaînage fragile vers une classe déjà masquée.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
from discord.ext import commands

from cogs import final_error_embed_v5 as erreurs
from cogs.bot_excellence_runtime import RuntimeRateLimitError
from utils import sentrix_panels as panels


class _FauxCtx:
    """Assez de surface pour construire un panneau d'erreur (voir test_messages_erreur.py)."""

    clean_prefix = "+"
    prefix = "+"
    invoked_with = "test"
    command = None
    guild = None


def _rendu(erreur) -> str:
    return panels.texte_complet(erreurs._prefix_error_panel(_FauxCtx(), erreur)).casefold()


def test_rate_limit_error_a_son_propre_message_pas_acces_refuse():
    texte = _rendu(RuntimeRateLimitError(5.0))
    assert "temporairement limité" in texte
    assert "réessayez" in texte
    assert "pas autorisé" not in texte


def test_rate_limit_error_affiche_le_delai_reel():
    texte = _rendu(RuntimeRateLimitError(42.0))
    assert "42" in texte


def test_tictactoe_sans_adversaire_declenche_le_matchmaking_pas_le_panneau_generique():
    bot = commands.Bot(command_prefix="+", intents=discord.Intents.none())
    erreurs.install(bot)

    fake_ctx = SimpleNamespace(
        command=SimpleNamespace(qualified_name="tictactoe"),
        _sentrix_response_sent=False,
    )
    param = SimpleNamespace(name="adversaire", displayed_name="adversaire")
    erreur = commands.MissingRequiredArgument(param)

    with patch(
        "cogs.bot_excellence_runtime._matchmake_tictactoe", new=AsyncMock()
    ) as mock_matchmake:
        asyncio.run(bot.on_command_error(fake_ctx, erreur))

    mock_matchmake.assert_awaited_once_with(fake_ctx)


def test_une_autre_commande_sans_argument_garde_le_panneau_generique():
    """Le court-circuit est specifique a +tictactoe : toute autre commande avec
    un argument manquant doit continuer a recevoir le panneau standard."""
    fake_ctx = SimpleNamespace(command=SimpleNamespace(qualified_name="ban"))
    param = SimpleNamespace(name="membre", displayed_name="membre")
    erreur = commands.MissingRequiredArgument(param)
    texte = panels.texte_complet(erreurs._prefix_error_panel(fake_ctx, erreur)).casefold()
    assert "argument manquant" in texte


def test_tictactoe_avec_un_autre_argument_manquant_garde_le_panneau_generique():
    """Seul le parametre 'adversaire' declenche le matchmaking."""
    fake_ctx = SimpleNamespace(command=SimpleNamespace(qualified_name="tictactoe"))
    param = SimpleNamespace(name="autre_chose", displayed_name="autre_chose")
    erreur = commands.MissingRequiredArgument(param)
    texte = panels.texte_complet(erreurs._prefix_error_panel(fake_ctx, erreur)).casefold()
    assert "argument manquant" in texte
