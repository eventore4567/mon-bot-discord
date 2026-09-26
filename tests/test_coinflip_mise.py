"""Pile ou face à la mise : même cycle d'argent que les autres jeux à mise.

``+coinflip`` était le dernier jeu à récompense fixe : douze pièces si on
devinait juste, rien à risquer. Il passe désormais par
``services.game_stakes`` — réservation atomique au départ, règlement en gain
ou en perte — exactement comme ``+bomb``, ``+lava`` et ``+rocket``. Recopier
une deuxième mécanique d'argent ici l'aurait fait diverger de celle qui est
déjà éprouvée.

Le mode sans mise est conservé tel quel : jouer sans rien risquer reste
possible, et c'est ce que fait la commande quand aucun montant n'est donné.
"""
from __future__ import annotations

import ast
import inspect
import os
import textwrap

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from cogs.games_economy import (
    COINFLIP_MISE_MAX,
    COINFLIP_MISE_MIN,
    COINFLIP_MULTIPLICATEUR,
    GamesRapides,
)


def test_le_retour_laisse_la_meme_marge_que_les_autres_jeux_a_mise():
    """97 % : sans marge le jeu ne coûterait jamais rien, au-delà de cinq
    points il devient punitif. La pièce étant équilibrée, le taux de retour
    est exactement le multiplicateur divisé par deux."""
    rtp = COINFLIP_MULTIPLICATEUR * 0.5
    assert abs(rtp - 0.97) < 0.005, f"taux de retour {rtp:.3f}"


def test_les_bornes_de_mise_sont_coherentes():
    assert 0 < COINFLIP_MISE_MIN < COINFLIP_MISE_MAX


def test_le_gain_maximal_reste_du_meme_ordre_que_les_autres_jeux():
    """+bomb plafonne à 52 380. Un pile ou face qui paierait bien davantage
    déséquilibrerait l'économie d'un serveur en une manche."""
    maximum = int(round(COINFLIP_MISE_MAX * COINFLIP_MULTIPLICATEUR))
    assert maximum <= 60_000, maximum


def test_la_mise_est_facultative():
    """Le mode sans risque doit survivre : c'est le comportement historique,
    et le balayage strict exécute toujours « +coinflip pile » sans montant."""
    signature = inspect.signature(GamesRapides.coinflip.callback)
    mise = signature.parameters["mise"]
    assert mise.default is None


def test_la_manche_a_mise_passe_par_le_cycle_partage():
    source = inspect.getsource(GamesRapides.coinflip.callback)
    for appel in ("game_stakes.nouvel_identifiant", "game_stakes.ouvrir_mise",
                  "game_stakes.regler_gain", "game_stakes.regler_perte"):
        assert appel in source, f"{appel} absent : une mécanique parallèle a été recopiée"


def test_la_manche_a_mise_ne_credite_pas_deux_fois():
    """``_finish`` crédite lui aussi quand on lui passe un montant. Sur une
    manche à mise, c'est ``game_stakes`` qui paie : ``_finish`` ne doit servir
    qu'au cooldown, au verrou et à l'historique, donc recevoir zéro."""
    # dedent, pas lstrip : lstrip ne désindente que la première ligne et laisse
    # le corps décalé, ce qui fait échouer ast.parse sur une IndentationError.
    arbre = ast.parse(textwrap.dedent(inspect.getsource(GamesRapides.coinflip.callback)))
    montants = []
    for noeud in ast.walk(arbre):
        if (isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name)
                and noeud.func.id == "_finish" and len(noeud.args) >= 6):
            montants.append(noeud.args[5])
    assert montants, "aucun appel à _finish trouvé : test à mettre à jour"
    zeros = [n for n in montants if isinstance(n, ast.Constant) and n.value == 0]
    assert zeros, "aucun _finish à montant nul : la manche à mise crédite deux fois"


def test_le_verrou_de_jeu_est_relache_si_la_mise_echoue():
    """Sans cela, un joueur au solde insuffisant reste bloqué jusqu'au
    redémarrage : le précontrôle a posé le verrou, la mise a échoué, et plus
    rien ne le relâche."""
    source = inspect.getsource(GamesRapides.coinflip.callback)
    avant = source.index('statut != "ok"')
    assert "release_play_lock" in source[avant:avant + 400]
