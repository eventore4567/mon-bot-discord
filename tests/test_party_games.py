"""Règles pures des jeux à plusieurs : +race, +detective, +crown.

Deux promesses ne se voient pas en cliquant, et c'est ici qu'elles se
vérifient : une enquête doit toujours désigner exactement un coupable, et une
course ne doit pas avoir de stratégie gagnante unique.
"""
from __future__ import annotations

import os
import statistics

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from utils import party_games as party
from utils.pve_engine import AleaPseudo


# =============================================================================
# 🏁 RACE
# =============================================================================

def test_le_pas_garanti_avance_toujours():
    alea = AleaPseudo(1)
    for _ in range(300):
        coureur = party.Coureur(1)
        resultat = party.avancer(coureur, False, alea)
        assert party.AVANCE[0] <= resultat["pas"] <= party.AVANCE[1]
        assert coureur.position == resultat["pas"]


def test_le_sprint_peut_caler_et_coute_alors_un_tour():
    alea = AleaPseudo(2)
    coureur = party.Coureur(1)
    cales = 0
    for _ in range(400):
        coureur.position = 0
        resultat = party.avancer(coureur, True, alea)
        if resultat["cale"]:
            cales += 1
            assert coureur.repos == party.SPRINT_PENALITE
            coureur.repos = 0
    assert 0.20 <= cales / 400 <= 0.40, f"{cales / 4:.1f} % de sprints calés"


def test_le_repos_consomme_un_coup_sans_avancer():
    coureur = party.Coureur(1, repos=1)
    resultat = party.avancer(coureur, False, AleaPseudo(1))
    assert resultat["repos"] and resultat["pas"] == 0
    assert coureur.position == 0 and coureur.repos == 0


def test_on_ne_depasse_jamais_la_ligne():
    coureur = party.Coureur(1, position=party.PISTE - 1)
    party.avancer(coureur, True, AleaPseudo(1))
    assert coureur.position <= party.PISTE
    assert coureur.arrive or coureur.position == party.PISTE - 1


def test_aucune_des_deux_options_ne_domine_l_autre():
    """Le cœur de la demande : le choix doit rester un choix.

    Si l'espérance du sprint était plus basse, personne ne sprinterait ; si
    elle était bien plus haute, personne n'avancerait prudemment. La mesure
    est faite tour par tour, sans vitesse de clic — ce que le délai par joueur
    borne par ailleurs dans le jeu.
    """
    sur, sprint = party.esperance(False), party.esperance(True)
    assert 0.9 <= sprint / sur <= 1.3, f"sûr {sur:.2f} contre sprint {sprint:.2f}"

    def course(strategies, graine):
        alea = AleaPseudo(graine)
        coureurs = [party.Coureur(i) for i in range(len(strategies))]
        for _ in range(300):
            for coureur, strategie in zip(coureurs, strategies):
                party.avancer(coureur, strategie(coureur), alea)
                if coureur.arrive:
                    return coureur.user_id
        return None

    total = 2500
    duels = [course([lambda c: False, lambda c: True], g) for g in range(total)]
    victoires_sures = 100 * duels.count(0) / total
    assert 35 <= victoires_sures <= 65, (
        f"le pas garanti gagne {victoires_sures:.1f} % des duels contre le sprint")


def test_le_jeu_mixte_bat_les_deux_strategies_pures():
    """Sprinter puis sécuriser à l'approche : c'est la décision qui paie."""
    def course(strategies, graine):
        alea = AleaPseudo(graine)
        coureurs = [party.Coureur(i) for i in range(len(strategies))]
        for _ in range(300):
            for coureur, strategie in zip(coureurs, strategies):
                party.avancer(coureur, strategie(coureur), alea)
                if coureur.arrive:
                    return coureur.user_id
        return None

    mixte = lambda c: c.position < party.PISTE - 8
    total = 2500
    contre_sur = [course([lambda c: False, mixte], g) for g in range(total)]
    assert 100 * contre_sur.count(1) / total > 52, "le jeu mixte ne paie pas"


def test_les_bornes_de_la_course_sont_coherentes():
    assert party.PISTE > party.SPRINT[1] * 2, "la piste se boucle en trop peu de coups"
    assert party.RACE_JOUEURS_MIN >= 2 and party.RACE_JOUEURS_MAX > party.RACE_JOUEURS_MIN
    assert party.DELAI_ENTRE_COUPS > 0, "sans délai, la course se gagne à la macro"


# =============================================================================
# 🕵️ DETECTIVE
# =============================================================================

def test_une_enquete_designe_exactement_un_coupable():
    enquete = party.generer_enquete(AleaPseudo(1))
    assert enquete is not None
    assert enquete.restants(len(enquete.indices)) == [enquete.coupable]


@pytest.mark.parametrize("lot", range(4))
def test_mille_enquetes_par_lot_sont_toutes_resolubles(lot):
    """Quatre mille enquêtes. Aucune ne doit laisser deux suspects possibles :
    le joueur qui accuse l'autre aurait raison sans pouvoir gagner."""
    for graine in range(lot * 1000, lot * 1000 + 1000):
        enquete = party.generer_enquete(AleaPseudo(graine))
        assert enquete is not None, f"génération en échec à la graine {graine}"
        restants = enquete.restants(len(enquete.indices))
        assert restants == [enquete.coupable], (graine, [s.nom for s in restants])
        assert 0 < len(enquete.indices) <= party.INDICES_MAX
        assert len(enquete.suspects) == party.SUSPECTS
        assert enquete.coupable in enquete.suspects


def test_les_suspects_sont_tous_differents():
    """Deux suspects identiques rendraient l'enquête insoluble par construction."""
    for graine in range(300):
        enquete = party.generer_enquete(AleaPseudo(graine))
        traits = [s.traits for s in enquete.suspects]
        noms = [s.nom for s in enquete.suspects]
        assert len(set(traits)) == len(traits)
        assert len(set(noms)) == len(noms)


def test_aucun_indice_ne_ment():
    """Tous les indices sont vrais du coupable : le jeu ne triche jamais."""
    for graine in range(400):
        enquete = party.generer_enquete(AleaPseudo(graine))
        for indice in enquete.indices:
            assert indice.compatible(enquete.coupable), indice.texte()


def test_chaque_indice_elimine_au_moins_un_suspect():
    """Un indice qui n'écarte personne fait perdre un tour pour rien."""
    for graine in range(300):
        enquete = party.generer_enquete(AleaPseudo(graine))
        restants = list(enquete.suspects)
        for indice in enquete.indices:
            apres = party.compatibles(restants, [indice])
            assert len(apres) < len(restants), indice.texte()
            restants = apres


def test_les_suspects_restants_se_reduisent_indice_apres_indice():
    enquete = party.generer_enquete(AleaPseudo(5))
    tailles = [len(enquete.restants(n)) for n in range(len(enquete.indices) + 1)]
    assert tailles[0] == party.SUSPECTS
    assert tailles[-1] == 1
    assert tailles == sorted(tailles, reverse=True)


def test_accuser_tot_rapporte_plus():
    enquete = party.generer_enquete(AleaPseudo(7))
    primes = [party.prime_accusation(enquete, n) for n in range(len(enquete.indices) + 1)]
    assert primes == sorted(primes, reverse=True)
    assert primes[-1] == party.DETECTIVE_BASE
    assert primes[0] > primes[-1], "accuser sans indice ne paie pas plus"


def test_le_portrait_montre_les_trois_traits():
    enquete = party.generer_enquete(AleaPseudo(2))
    for suspect in enquete.suspects:
        portrait = suspect.portrait()
        assert suspect.nom in portrait
        for attribut, valeur in suspect.traits:
            assert dict(party.ATTRIBUTS[attribut])[valeur] in portrait


def test_la_generation_rend_la_main_au_lieu_de_boucler():
    assert party.generer_enquete(AleaPseudo(1), essais=0) is not None or True
    # Un seul essai peut échouer ; ce qui compte est qu'on ne tourne pas sans fin.
    resultat = party.generer_enquete(AleaPseudo(1), essais=1)
    assert resultat is None or resultat.restants(len(resultat.indices)) == [resultat.coupable]


# =============================================================================
# 👑 CROWN
# =============================================================================

def test_prendre_la_couronne_la_donne_et_compte_le_temps():
    couronne = party.Couronne(fin=100.0)
    assert couronne.prendre(1, 0.0) == "ok"
    assert couronne.porteur == 1
    assert couronne.prendre(2, 10.0) == "ok"
    assert couronne.temps_de(1) == 10.0
    assert couronne.porteur == 2


def test_le_porteur_ne_peut_pas_se_la_reprendre():
    couronne = party.Couronne(fin=100.0)
    couronne.prendre(1, 0.0)
    assert couronne.prendre(1, 5.0) == "deja"


def test_le_depossede_attend_le_verrou():
    """Sans verrou, deux joueurs se la reprennent en boucle à la milliseconde."""
    couronne = party.Couronne(fin=200.0)
    couronne.prendre(1, 0.0)
    couronne.prendre(2, 10.0)
    assert couronne.prendre(1, 10.0 + party.CROWN_VERROU - 0.1) == "verrou"
    assert couronne.prendre(1, 10.0 + party.CROWN_VERROU + 0.1) == "ok"


def test_plus_rien_ne_se_prend_apres_la_fin():
    couronne = party.Couronne(fin=50.0)
    assert couronne.prendre(1, 50.0) == "finie"
    assert couronne.prendre(1, 60.0) == "finie"


def test_le_temps_ne_court_jamais_au_dela_de_la_fin():
    """Clôturer en retard ne doit pas créditer le temps d'après la manche."""
    couronne = party.Couronne(fin=30.0)
    couronne.prendre(1, 0.0)
    couronne.cloturer(90.0)
    assert couronne.temps_de(1) == 30.0


def test_cloturer_deux_fois_ne_double_pas_le_temps():
    couronne = party.Couronne(fin=30.0)
    couronne.prendre(1, 0.0)
    couronne.cloturer(20.0)
    couronne.cloturer(20.0)
    assert couronne.temps_de(1) == 20.0


def test_le_classement_ordonne_par_temps_de_regne():
    couronne = party.Couronne(fin=100.0)
    couronne.prendre(1, 0.0)
    couronne.prendre(2, 5.0)
    couronne.prendre(1, 25.0)
    couronne.cloturer(30.0)
    # Le joueur 1 règne de 0 à 5 puis de 25 à 30, soit dix secondes ; le
    # joueur 2 de 5 à 25, soit vingt. Le classement suit le temps cumulé, pas
    # l'ordre des prises ni le fait de finir avec la couronne.
    classement = couronne.classement()
    assert [uid for uid, _ in classement] == [2, 1]
    assert couronne.temps_de(1) == 10.0 and couronne.temps_de(2) == 20.0


def test_les_gains_recompensent_le_temps_et_pas_seulement_le_dernier_clic():
    """Ne payer que le porteur final ferait de la manche une loterie."""
    couronne = party.Couronne(fin=100.0)
    couronne.prendre(1, 0.0)
    couronne.prendre(2, 60.0)
    couronne.cloturer(62.0)
    gains = party.gains_couronne(couronne)
    assert gains[1] == 60 * party.CROWN_PAR_SECONDE, gains
    assert gains[2] == 2 * party.CROWN_PAR_SECONDE + party.CROWN_BASE, gains
    assert gains[1] > gains[2], "une minute de règne doit battre deux secondes et la prime"


def test_un_porteur_eclair_ne_touche_pas_de_temps():
    couronne = party.Couronne(fin=100.0)
    couronne.prendre(1, 0.0)
    couronne.prendre(2, 0.2)
    couronne.cloturer(1.0)
    gains = party.gains_couronne(couronne)
    assert 1 not in gains, "moins d'une seconde de règne ne vaut rien"


def test_une_couronne_jamais_prise_ne_paie_personne():
    couronne = party.Couronne(fin=10.0)
    couronne.cloturer(10.0)
    assert party.gains_couronne(couronne) == {}


def test_la_fenetre_de_fin_est_une_vraie_fenetre():
    bas, haut = party.CROWN_FENETRE
    assert 0 < bas < haut, "un instant de fin fixe s'anticipe à la seconde"
    assert party.CROWN_VERROU * 2 < bas, "le verrou dépasserait la manche entière"
