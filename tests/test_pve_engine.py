"""Moteur PvE partagé par +dragon et +zombie.

Ce qui est vérifié ici ne peut pas l'être en cliquant : qu'aucune stratégie
triviale ne gagne presque tout, que les vagues montent réellement en
difficulté, et que rien n'est décidé après avoir lu le choix du joueur.
"""
from __future__ import annotations

import os
import statistics

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from utils import pve_engine as pve


# =============================================================================
# Aléa
# =============================================================================

def test_l_alea_de_production_passe_par_secrets():
    """Un Mersenne Twister est prévisible ; ces manches versent de l'argent."""
    import inspect

    source = inspect.getsource(pve.AleaSecurise.entier)
    assert "game_rewards" in source and "secure_randint" in source


def test_l_alea_graine_est_reproductible():
    a, b = pve.AleaPseudo(7), pve.AleaPseudo(7)
    assert [a.entier(1, 100) for _ in range(20)] == [b.entier(1, 100) for _ in range(20)]


def test_chance_respecte_ses_bornes():
    alea = pve.AleaPseudo(1)
    assert alea.chance(0) is False
    assert alea.chance(1) is True
    tirages = sum(alea.chance(0.25) for _ in range(4000))
    assert 850 <= tirages <= 1150, f"25 % attendu, obtenu {tirages / 40:.1f} %"


def test_pondere_respecte_les_poids():
    alea = pve.AleaPseudo(3)
    paires = [("a", 90), ("b", 10)]
    tirages = [alea.pondere(paires) for _ in range(4000)]
    assert 0.85 <= tirages.count("a") / 4000 <= 0.95


# =============================================================================
# 🐉 Dragon
# =============================================================================

def test_les_quatre_dragons_couvrent_les_trois_difficultes():
    niveaux = {d.difficulte for d in pve.DRAGONS.values()}
    assert niveaux == set(pve.DIFFICULTES_DRAGON)
    assert len(pve.DRAGONS) >= 4


def test_chaque_dragon_a_un_profil_distinct():
    """Quatre dragons identiques sous des noms différents ne sont qu'un dragon."""
    profils = {(d.pv, d.degats, d.armure, d.esquive, d.poids_souffle)
               for d in pve.DRAGONS.values()}
    assert len(profils) == len(pve.DRAGONS)


def test_les_intentions_sont_tirees_avant_le_premier_coup():
    """Décider après avoir lu le coup du joueur permettrait de souffler
    exactement quand il n'a pas paré : le combat serait truqué."""
    etat = pve.EtatDragon(dragon=pve.DRAGONS["feu"], alea=pve.AleaPseudo(5))
    scelle = list(etat.intentions)
    assert len(scelle) >= pve.TOURS_MAX_DRAGON
    for _ in range(6):
        if etat.fini:
            break
        etat.jouer("attaque")
    assert etat.intentions == scelle, "les intentions ont bougé pendant le combat"


def test_deux_souffles_de_suite_sont_impossibles():
    """Parer le premier souffle laisse sans rage ; deux d'affilée tueraient
    un joueur qui a pourtant fait la bonne lecture."""
    for graine in range(200):
        suite = pve.intentions_dragon(pve.DRAGONS["ombre"], pve.AleaPseudo(graine),
                                      pve.TOURS_MAX_DRAGON)
        paires = list(zip(suite, suite[1:]))
        assert not any(a == b == pve.SOUFFLE for a, b in paires)


def test_le_souffle_fait_mal_et_la_parade_le_reduit():
    dragon = pve.DRAGONS["feu"]
    alea = pve.AleaPseudo(11)
    souffles = [pve.degats_dragon(dragon, "attaque", pve.SOUFFLE, alea) for _ in range(400)]
    griffes = [pve.degats_dragon(dragon, "attaque", pve.GRIFFE, alea) for _ in range(400)]
    pares = [pve.degats_dragon(dragon, "defense", pve.SOUFFLE, alea) for _ in range(400)]
    assert statistics.mean(souffles) > statistics.mean(griffes) * 1.8
    assert statistics.mean(pares) < statistics.mean(souffles) * 0.5


def test_le_dragon_s_enrage_avec_les_tours():
    """Sans cela, temporiser est gratuit et parer en boucle gagne toujours."""
    dragon = pve.DRAGONS["feu"]
    tot = pve.AleaPseudo(2)
    tard = pve.AleaPseudo(2)
    debut = [pve.degats_dragon(dragon, "attaque", pve.GRIFFE, tot, 0) for _ in range(300)]
    fin = [pve.degats_dragon(dragon, "attaque", pve.GRIFFE, tard, 16) for _ in range(300)]
    assert statistics.mean(fin) > statistics.mean(debut)


def test_la_capacite_speciale_ignore_armure_et_esquive():
    dragon = pve.DRAGONS["glace"]     # la plus blindée
    alea = pve.AleaPseudo(4)
    for _ in range(300):
        degats, critique, esquive = pve.degats_joueur(dragon, "special", pve.GRIFFE, alea)
        assert not esquive and not critique
        assert pve.DEGATS_SPECIAL[0] <= degats <= pve.DEGATS_SPECIAL[1]


def test_la_capacite_speciale_exige_la_rage_maximale():
    etat = pve.EtatDragon(dragon=pve.DRAGONS["feu"], alea=pve.AleaPseudo(1))
    assert "special" not in etat.actions_possibles()
    with pytest.raises(ValueError):
        etat.jouer("special")


def test_la_rage_ne_vient_ni_seulement_de_la_defense_ni_seulement_de_l_attaque():
    """Le monopole de la rage crée à lui seul une stratégie triviale."""
    assert pve.RAGE_PAR_ATTAQUE > 0 and pve.RAGE_PAR_PARADE > 0
    assert pve.RAGE_PARADE_SOUFFLE > pve.RAGE_PAR_PARADE


def test_parer_une_garde_ne_rapporte_aucune_rage():
    etat = pve.EtatDragon(dragon=pve.DRAGONS["feu"], alea=pve.AleaPseudo(1))
    etat.intentions = [pve.GARDE] * (pve.TOURS_MAX_DRAGON + 1)
    etat.jouer("defense")
    assert etat.rage == 0


def test_les_soins_sont_comptes_et_ne_depassent_pas_le_maximum():
    etat = pve.EtatDragon(dragon=pve.DRAGONS["feu"], alea=pve.AleaPseudo(1))
    etat.pv_joueur = pve.PV_JOUEUR - 5
    resume = etat.jouer("soin")
    # Le soin est plafonné à ce qui manque, pas à SOIN_POINTS. On mesure le
    # soin lui-même : à la fin du tour le dragon a déjà riposté, et les PV
    # affichés ne diraient plus rien de ce qu'a rendu la potion.
    assert resume["soigne"] == 5, "un soin déborde le maximum"
    assert etat.soins == pve.SOINS_DRAGON - 1
    etat.soins = 0
    assert "soin" not in etat.actions_possibles()


def test_le_joueur_frappe_avant_de_subir():
    """Un dragon abattu ne riposte pas : sinon le dernier coup gagnant
    transformerait beaucoup de victoires en égalités incompréhensibles."""
    etat = pve.EtatDragon(dragon=pve.DRAGONS["dragonnet"], alea=pve.AleaPseudo(1))
    etat.pv_dragon = 1
    etat.pv_joueur = 100
    etat.intentions = [pve.SOUFFLE] * (pve.TOURS_MAX_DRAGON + 1)
    etat.jouer("special") if "special" in etat.actions_possibles() else etat.jouer("attaque")
    if etat.pv_dragon <= 0:
        assert etat.pv_joueur == 100, "le dragon mort a quand même riposté"


def test_l_issue_ne_donne_pas_la_victoire_a_un_joueur_mort():
    etat = pve.EtatDragon(dragon=pve.DRAGONS["feu"], alea=pve.AleaPseudo(1))
    etat.pv_joueur = 0
    etat.pv_dragon = 0
    assert etat.issue() == "egalite"


def test_les_tours_epuises_ne_sont_pas_une_victoire():
    """Gagner aux points en survivant sans frapper serait une stratégie triviale."""
    etat = pve.EtatDragon(dragon=pve.DRAGONS["feu"], alea=pve.AleaPseudo(1))
    etat.tour = pve.TOURS_MAX_DRAGON
    etat.pv_joueur = 99
    etat.pv_dragon = 1
    assert etat.fini and etat.issue() == "defaite"


def test_une_action_indisponible_est_refusee():
    etat = pve.EtatDragon(dragon=pve.DRAGONS["feu"], alea=pve.AleaPseudo(1))
    with pytest.raises(ValueError):
        etat.jouer("valser")


def _victoires(dragon, strategie, n):
    gagnees = 0
    for graine in range(n):
        etat = pve.EtatDragon(dragon=dragon, alea=pve.AleaPseudo(graine))
        while not etat.fini:
            etat.jouer(strategie(etat))
        gagnees += etat.issue() == "victoire"
    return 100 * gagnees / n


def _toujours_attaque(e):
    return "attaque"


def _boucle_speciale(e):
    possibles = e.actions_possibles()
    return "special" if "special" in possibles else ("defense" if e.rage < 3 else "attaque")


def _jeu_informe(e):
    possibles = e.actions_possibles()
    if "special" in possibles and e.intention != pve.GARDE:
        return "special"
    if e.intention == pve.SOUFFLE:
        return "defense"
    if e.pv_joueur <= 35 and "soin" in possibles:
        return "soin"
    return "attaque"


@pytest.mark.parametrize("cle", sorted(pve.DRAGONS))
def test_aucune_strategie_triviale_ne_gagne_presque_tout(cle):
    """La demande exacte de Jayden, mesurée plutôt qu'affirmée.

    Deux stratégies sans réflexion sont testées : marteler « Attaquer », et
    parer jusqu'à la rage pour lâcher la capacité spéciale — c'est la seconde
    qui gagnait 99 % des combats avant que la rage cesse d'être le monopole de
    la défense.
    """
    dragon = pve.DRAGONS[cle]
    for nom, strategie in (("attaque", _toujours_attaque), ("spéciale", _boucle_speciale)):
        taux = _victoires(dragon, strategie, 900)
        assert taux <= 60, f"{cle} : la stratégie « {nom} » gagne {taux:.1f} %"


@pytest.mark.parametrize("cle", sorted(pve.DRAGONS))
def test_le_jeu_informe_bat_nettement_le_martelage(cle):
    """Un jeu où réfléchir ne paie pas n'est pas un jeu."""
    dragon = pve.DRAGONS[cle]
    informe = _victoires(dragon, _jeu_informe, 900)
    martelage = _victoires(dragon, _toujours_attaque, 900)
    assert informe > martelage + 15, (
        f"{cle} : informé {informe:.1f} % contre martelage {martelage:.1f} %")


def test_les_difficultes_sont_reellement_ordonnees():
    par_difficulte: dict[str, list[float]] = {}
    for dragon in pve.DRAGONS.values():
        par_difficulte.setdefault(dragon.difficulte, []).append(
            _victoires(dragon, _jeu_informe, 700))
    moyennes = {k: statistics.mean(v) for k, v in par_difficulte.items()}
    assert moyennes["facile"] > moyennes["normal"] > moyennes["difficile"], moyennes


# =============================================================================
# 🧟 Zombie
# =============================================================================

def test_les_quatre_types_de_zombies_existent_et_different():
    assert set(pve.ZOMBIES) == {"normal", "rapide", "tank", "boss"}
    assert pve.ZOMBIES["rapide"].coups > 1, "le coureur doit frapper deux fois"
    assert pve.ZOMBIES["tank"].pv > pve.ZOMBIES["normal"].pv
    assert pve.ZOMBIES["boss"].pv > pve.ZOMBIES["tank"].pv


def test_la_composition_ne_depend_que_du_numero_de_vague():
    """Aucune vague ne doit être générée après avoir vu le choix du joueur."""
    for numero in range(1, pve.VAGUES_MAX + 1):
        premiere = [z.cle for z in pve.composer_vague(numero)]
        for _ in range(5):
            assert [z.cle for z in pve.composer_vague(numero)] == premiere


def test_la_difficulte_des_vagues_croit_strictement():
    pvs = [pve.pv_vague(n) for n in range(1, pve.VAGUES_MAX + 1)]
    degats = [pve.degats_vague(n) for n in range(1, pve.VAGUES_MAX + 1)]
    assert pvs == sorted(pvs) and len(set(pvs)) == len(pvs), pvs
    assert degats == sorted(degats) and len(set(degats)) == len(degats), degats


def test_le_boss_apparu_ne_disparait_plus():
    """Un boss qui s'en va rend la vague suivante plus facile que la précédente."""
    vu = False
    for numero in range(1, pve.VAGUES_MAX + 1):
        present = any(z.cle == "boss" for z in pve.composer_vague(numero))
        if vu:
            assert present, f"le boss manque à la vague {numero}"
        vu = vu or present
    assert vu, "aucun boss dans tout le jeu"


def test_la_pression_monte_avec_les_vagues():
    valeurs = [pve.pression_vague(n) for n in range(1, pve.VAGUES_MAX + 1)]
    assert valeurs == sorted(valeurs) and valeurs[0] < valeurs[-1]


def test_tirer_coute_des_munitions_et_devient_impossible_sans():
    etat = pve.EtatZombie(alea=pve.AleaPseudo(1))
    avant = etat.munitions
    etat.jouer("tirer")
    assert etat.munitions == avant - pve.COUT_TIR
    etat.munitions = 0
    assert "tirer" not in etat.actions_possibles()
    with pytest.raises(ValueError):
        etat.jouer("tirer")


def test_les_retranchements_sont_une_ressource_limitee():
    """Sans limite, se retrancher en boucle survit indéfiniment sans progresser."""
    etat = pve.EtatZombie(alea=pve.AleaPseudo(1))
    for _ in range(pve.BARRICADES):
        assert "barricader" in etat.actions_possibles()
        etat.jouer("barricader")
    assert etat.barricades_restantes == 0
    assert "barricader" not in etat.actions_possibles()


def test_se_retrancher_soigne_sans_deborder():
    etat = pve.EtatZombie(alea=pve.AleaPseudo(1))
    etat.pv = pve.PV_SURVIVANT - 3
    resume = etat.jouer("barricader")
    # Mesuré sur le soin rendu : la horde riposte dans le même tour, et les PV
    # de fin de tour ne distingueraient pas un soin plafonné d'un soin mangé.
    assert resume["soigne"] == 3, "le retranchement déborde le maximum"
    assert etat.pv <= pve.PV_SURVIVANT


def test_fouiller_ne_depasse_jamais_le_sac():
    etat = pve.EtatZombie(alea=pve.AleaPseudo(1))
    etat.munitions = pve.MUNITIONS_MAX
    etat.jouer("fouiller")
    assert etat.munitions == pve.MUNITIONS_MAX


def test_on_ne_peut_pas_farmer_eternellement():
    """Fouiller sans jamais tirer doit finir mal, pas durer sans fin."""
    etat = pve.EtatZombie(alea=pve.AleaPseudo(1))
    tours = 0
    while not etat.fini and tours < pve.TOURS_MAX_ZOMBIE * 3:
        etat.jouer("fouiller")
        tours += 1
    assert etat.fini and tours <= pve.TOURS_MAX_ZOMBIE
    assert etat.vagues_terminees == 0, "fouiller en boucle ne doit rien nettoyer"


def _survie(strategie, n):
    resultats = []
    for graine in range(n):
        etat = pve.EtatZombie(alea=pve.AleaPseudo(graine))
        while not etat.fini:
            etat.jouer(strategie(etat))
        resultats.append(etat)
    return resultats


def _tout_tirer(e):
    return "tirer" if "tirer" in e.actions_possibles() else "melee"


def _survivant_informe(e):
    possibles = e.actions_possibles()
    if e.pv <= 25 and "barricader" in possibles and e.pv_vague_restants > 30:
        return "barricader"
    if e.munitions < pve.COUT_TIR:
        return "fouiller" if e.pv > 30 else "melee"
    if e.munitions <= 4 and e.pv > 55:
        return "fouiller"
    return "tirer"


@pytest.mark.parametrize("action", sorted(pve.ACTIONS_ZOMBIE))
def test_aucune_action_repetee_seule_ne_nettoie_le_jeu(action):
    def seule(e, action=action):
        return action if action in e.actions_possibles() else "melee"

    vagues = [x.vagues_terminees for x in _survie(seule, 250)]
    assert max(vagues) < pve.VAGUES_MAX, (
        f"marteler « {action} » nettoie les {pve.VAGUES_MAX} vagues")


def test_le_survivant_informe_bat_le_martelage_du_tir():
    informe = _survie(_survivant_informe, 900)
    brut = _survie(_tout_tirer, 900)
    moyenne_informe = statistics.mean(x.vagues_terminees for x in informe)
    moyenne_brute = statistics.mean(x.vagues_terminees for x in brut)
    assert moyenne_informe > moyenne_brute, (informe, brut)
    finis_informe = sum(x.vagues_terminees >= pve.VAGUES_MAX for x in informe)
    finis_brut = sum(x.vagues_terminees >= pve.VAGUES_MAX for x in brut)
    assert finis_informe > finis_brut * 3, (finis_informe, finis_brut)


def test_la_partie_se_termine_toujours():
    for strategie in (_tout_tirer, _survivant_informe, lambda e: "melee"):
        for graine in range(120):
            etat = pve.EtatZombie(alea=pve.AleaPseudo(graine))
            tours = 0
            while not etat.fini:
                etat.jouer(strategie(etat))
                tours += 1
                assert tours <= pve.TOURS_MAX_ZOMBIE + 1, "boucle sans fin"


def test_les_points_de_vie_ne_passent_jamais_sous_zero():
    for graine in range(300):
        etat = pve.EtatZombie(alea=pve.AleaPseudo(graine))
        while not etat.fini:
            etat.jouer(_tout_tirer(etat))
            assert etat.pv >= 0 and etat.munitions >= 0
            assert etat.pv_vague_restants >= 0
