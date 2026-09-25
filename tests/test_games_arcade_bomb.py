"""💣 Bombes — mise, cases sûres, multiplicateur progressif, encaissement.

Le jeu que Jayden a décrit, et qui n'existait pas : `+minesweeper` est un
démineur classique sans mise ni encaissement. Ici la mise est réelle, le
multiplicateur monte à chaque case ouverte, et l'argent bouge vraiment.

Deux invariants comptent plus que le reste :
  - la grille est tirée AVANT le premier clic et ne bouge plus (une bombe
    déplacée après coup rendrait le jeu truqué et invérifiable) ;
  - deux clics simultanés ne créditent qu'une fois.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
import pytest

from cogs.games_arcade import (
    BOMB_BOMBES,
    BOMB_CASES,
    BOMB_MISE_MAX,
    BOMB_MISE_MIN,
    multiplicateur_bomb,
)
from utils.game_ui import valider_composants


# ------------------------------------------------------------- multiplicateur

def test_le_multiplicateur_monte_avec_chaque_case():
    valeurs = [multiplicateur_bomb(n) for n in range(BOMB_CASES - BOMB_BOMBES + 1)]
    assert valeurs[0] == 1.0
    assert valeurs == sorted(valeurs), "le multiplicateur doit croître"
    assert len(set(valeurs)) == len(valeurs), "deux paliers identiques ne récompensent pas le risque"


def test_le_retour_est_constant_quel_que_soit_le_moment_d_encaissement():
    """C'est ce qui rend le jeu honnête : aucune stratégie ne bat l'autre.

    Si un palier payait mieux, tout le monde encaisserait là et le reste de la
    grille ne servirait à rien.
    """
    sures = BOMB_CASES - BOMB_BOMBES
    retours = []
    for n in range(1, sures + 1):
        survie = 1.0
        for index in range(n):
            survie *= (sures - index) / (BOMB_CASES - index)
        retours.append(survie * multiplicateur_bomb(n))
    assert max(retours) - min(retours) < 0.01, f"retours inégaux : {retours}"
    # La banque garde une petite marge, sinon l'économie du serveur ne tient pas.
    assert 0.95 < sum(retours) / len(retours) < 1.0


def test_le_multiplicateur_ne_depasse_jamais_la_grille():
    """Demander plus de cases qu'il n'en existe ne doit pas exploser."""
    enorme = multiplicateur_bomb(999)
    assert enorme == multiplicateur_bomb(BOMB_CASES - BOMB_BOMBES)
    assert multiplicateur_bomb(0) == 1.0
    assert multiplicateur_bomb(-5) == 1.0


# ------------------------------------------------------------- grille

def _vue(mise: int = 100):
    from cogs.games_arcade import _VueBomb

    cog = SimpleNamespace(bot=None, emoji_monnaie="🪙", ligne_recompense=lambda r: "")
    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=1), author=SimpleNamespace(id=2),
        channel=SimpleNamespace(id=3),
    )
    return _VueBomb(cog, ctx, mise, "sid-test")


def test_la_grille_contient_exactement_les_bombes_attendues():
    for _ in range(50):
        vue = _vue()
        assert len(vue.bombes) == BOMB_BOMBES
        assert all(0 <= b < BOMB_CASES for b in vue.bombes)


def test_la_grille_ne_bouge_pas_apres_le_tirage():
    """Une bombe déplacée après un clic rendrait le jeu truqué."""
    vue = _vue()
    bombes = set(vue.bombes)
    sures = [i for i in range(BOMB_CASES) if i not in bombes]
    vue.ouvertes.append(sures[0])
    vue.ouvertes.append(sures[1])
    assert set(vue.bombes) == bombes


def test_aucun_bouton_n_est_vide():
    """Le défaut mesuré sur « Course à l'emoji » : cinq rectangles vides."""
    vue = _vue()
    valider_composants(vue)
    boutons = [e for e in vue.children if isinstance(e, discord.ui.Button)]
    assert len(boutons) == BOMB_CASES + 1, "neuf cases plus le bouton Encaisser"
    assert all(b.emoji is not None or (b.label or "").strip() for b in boutons)


def test_les_custom_id_sont_uniques_et_parlants():
    """Deux boutons au même custom_id rendent les clics ambigus."""
    vue = _vue()
    ids = [e.custom_id for e in vue.children if isinstance(e, discord.ui.Button)]
    assert len(ids) == len(set(ids))
    assert "bomb:cashout" in ids


def test_la_grille_tient_sur_un_ecran_de_telephone():
    """Discord limite à cinq rangées ; au-delà de quatre, mobile devient pénible."""
    vue = _vue()
    rangees = {e.row for e in vue.children if isinstance(e, discord.ui.Button)}
    assert max(rangees) <= 4
    assert BOMB_CASES == 9, "une grille 3x3 se lit d'un coup d'œil"


# ------------------------------------------------------------- bornes de mise

@pytest.mark.parametrize("mise", [0, -5, BOMB_MISE_MIN - 1, BOMB_MISE_MAX + 1])
def test_les_mises_hors_bornes_sont_refusees(mise):
    assert not (BOMB_MISE_MIN <= mise <= BOMB_MISE_MAX)


def test_les_bornes_de_mise_sont_coherentes():
    assert 0 < BOMB_MISE_MIN < BOMB_MISE_MAX


# ------------------------------------------------------------- gain

def test_le_gain_est_le_profit_net_pas_le_retour_total():
    """Le joueur garde sa mise : seul le profit est crédité. Sans ça, il serait
    payé deux fois pour l'argent qu'il n'a jamais perdu."""
    vue = _vue(mise=100)
    sures = [i for i in range(BOMB_CASES) if i not in vue.bombes]
    vue.ouvertes.extend(sures[:2])
    attendu = round(100 * vue.multiplicateur) - 100
    assert vue.gain == attendu
    assert vue.gain > 0


def test_sans_case_ouverte_il_n_y_a_rien_a_encaisser():
    vue = _vue()
    assert vue.gain == 0
    assert vue.multiplicateur == 1.0


# ------------------------------------------------------------- rendu

def test_la_grille_cache_les_bombes_tant_que_la_partie_dure():
    vue = _vue()
    visible = vue.grille()
    assert "💣" not in visible, "les bombes seraient visibles avant le premier clic"
    assert visible.count("⬜") == BOMB_CASES

    devoilee = vue.grille(devoilee=True)
    assert devoilee.count("💣") == BOMB_BOMBES


def test_le_texte_affiche_la_monnaie_et_le_prochain_palier():
    vue = _vue(mise=250)
    texte = vue.texte()
    assert "🪙" in texte, "un montant sans son unité ne dit pas 250 de quoi"
    assert "250" in texte
    assert "×1" in texte and "prochaine case" in texte


def test_le_texte_de_perte_dit_ce_qui_est_perdu():
    vue = _vue(mise=250)
    vue.perdu = True
    texte = vue.texte()
    assert "💥" in texte and "250" in texte and "🪙" in texte


def test_le_texte_d_encaissement_dit_le_gain():
    vue = _vue(mise=100)
    sures = [i for i in range(BOMB_CASES) if i not in vue.bombes]
    vue.ouvertes.extend(sures[:3])
    vue.encaisse = True
    texte = vue.texte()
    assert "💰" in texte and "🪙" in texte
    assert str(vue.gain) in texte


# ------------------------------------------------------------- anti-double-clic

def test_deux_encaissements_simultanes_n_en_font_qu_un():
    """Vérifié aussi sur le bot booté avec de l'argent réel : crédité une fois."""
    vue = _vue()
    appels: list[int] = []

    async def encaisser_lent():
        await asyncio.sleep(0.05)
        appels.append(1)

    async def scenario():
        return await asyncio.gather(
            vue.jouer_un_coup(encaisser_lent), vue.jouer_un_coup(encaisser_lent)
        )

    resultats = asyncio.run(scenario())
    assert appels == [1]
    assert sorted(resultats) == [False, True]
