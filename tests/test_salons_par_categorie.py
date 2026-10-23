"""Confiner une catégorie à certains salons, pas seulement bloquer un salon.

Jusqu'ici cogs/command_channel_gate n'offrait que des listes de BLOCAGE :
tout un salon, ou une commande précise dans un salon. « Les jeux
seulement dans #jeux » était donc impossible à exprimer autrement qu'en
bloquant les 74 commandes de jeu dans chaque autre salon, un par un.

La liste d'AUTORISATION par catégorie utilise la table de catégories
créée le même jour (utils/command_categories), celle que /help et
/commands partagent déjà.

Règle de sûreté : sans aucune ligne pour une catégorie, rien ne change.
Les serveurs qui n'ont rien configuré gardent le comportement d'avant.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from cogs import command_channel_gate as porte


def _bot(lignes):
    bot = MagicMock()
    bot.db.execute = AsyncMock()
    bot.db.fetchall = AsyncMock(return_value=[{"channel_id": c} for c in lignes])
    return bot


def _hors(lignes, salon, commande="dragon", cog="GamesArcade"):
    return asyncio.run(porte.categorie_hors_salon(_bot(lignes), 1, salon, commande, cog))


def test_sans_configuration_rien_ne_change():
    """Le cas de tous les serveurs existants."""
    hors, autorises = _hors([], 999)
    assert hors is False
    assert autorises == set()


def test_un_jeu_hors_du_salon_autorise_est_refuse():
    hors, autorises = _hors([42], 999)
    assert hors is True
    assert autorises == {42}


def test_un_jeu_dans_le_salon_autorise_passe():
    assert _hors([42], 42)[0] is False


def test_la_restriction_ne_touche_que_sa_categorie():
    """Confiner les jeux ne doit pas confiner la modération."""
    hors_jeu, _ = _hors([42], 999, "dragon", "GamesArcade")
    bot = MagicMock()
    bot.db.execute = AsyncMock()
    # La modération n'a aucune ligne : fetchall ne renvoie rien pour elle.
    bot.db.fetchall = AsyncMock(return_value=[])
    hors_mod, _ = asyncio.run(porte.categorie_hors_salon(bot, 1, 999, "ban", "Moderation"))
    assert hors_jeu is True
    assert hors_mod is False


def test_une_panne_de_lecture_ne_bloque_jamais_une_commande():
    """Fail-safe : sans réponse de la base, la commande passe."""
    bot = MagicMock()
    bot.db.execute = AsyncMock()
    bot.db.fetchall = AsyncMock(side_effect=RuntimeError("base indisponible"))
    assert asyncio.run(porte.categorie_hors_salon(bot, 1, 999, "dragon", "GamesArcade"))[0] is False


def test_le_refus_dit_ou_aller():
    """Un refus sec oblige le membre à deviner."""
    message = porte.message_hors_salon({42, 43})
    assert "<#42>" in message and "<#43>" in message


def test_le_refus_reste_court_avec_beaucoup_de_salons():
    message = porte.message_hors_salon(set(range(100, 112)))
    assert message.count("<#") == 5
    assert "autre(s)" in message


@pytest.mark.parametrize("surface", ["prefix_gate", "slash_gate"])
def test_les_deux_surfaces_passent_par_le_meme_controle(surface):
    import inspect

    src = inspect.getsource(porte.install)
    assert src.count("categorie_hors_salon") == 2, (
        "le contrôle doit valoir pour les commandes + ET les commandes /"
    )
