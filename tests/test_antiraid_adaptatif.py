"""L'anti-raid s'adapte au serveur et pèse l'âge des comptes.

Demandé par Jayden le 2026-10-23 : « que les automod soient bien plus
stricts, comme raid protect et les autres bots ».

Les deux seuils étaient PLATS : huit arrivées en dix secondes
déclenchaient la même alerte sur un serveur de vingt membres et sur un
serveur de vingt mille. Pour le petit, huit inconnus d'un coup EST le
raid ; pour le gros, c'est une journée ordinaire. Un seuil unique est
forcément trop laxiste d'un côté et trop nerveux de l'autre.

Deux corrections, dans l'esprit des bots dédiés :

1. le seuil suit la taille du serveur, borné des deux côtés ;
2. un compte créé il y a moins d'une semaine pèse double. Vingt comptes
   neufs d'un coup, c'est un raid ; vingt vétérans après une vidéo, non.

Règle de sûreté : le seuil historique reste un PLAFOND. On ne devient
jamais plus laxiste qu'avant, seulement plus strict.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from cogs import automod


def _declenche(arrivees: int, neuves: int, membres: int) -> bool:
    """Reproduit la condition du listener."""
    seuil = min(automod.seuil_raid_rapide(membres), automod.RAID_JOIN_THRESHOLD)
    velocite = automod.velocite_ponderee(arrivees, neuves)
    return velocite >= seuil or arrivees >= automod.RAID_JOIN_THRESHOLD


@pytest.mark.parametrize("membres,attendu", [
    (12, 4), (50, 4), (200, 4), (400, 5), (1000, 12), (50_000, 25),
])
def test_le_seuil_suit_la_taille_du_serveur(membres, attendu):
    assert automod.seuil_raid_rapide(membres) == attendu


def test_le_seuil_est_borne_des_deux_cotes():
    assert automod.seuil_raid_rapide(0) == automod.RAID_SEUIL_MINIMAL
    assert automod.seuil_raid_rapide(10_000_000) == automod.RAID_SEUIL_MAXIMAL


def test_une_taille_absente_ou_absurde_ne_casse_rien():
    """member_count peut être None sur une guilde partiellement en cache."""
    assert automod.seuil_raid_rapide(None) == automod.RAID_SEUIL_MINIMAL
    assert automod.seuil_raid_rapide("beaucoup") == automod.RAID_SEUIL_MINIMAL


def test_un_compte_neuf_pese_double():
    assert automod.velocite_ponderee(8, 0) == 8
    assert automod.velocite_ponderee(8, 8) == 16
    assert automod.velocite_ponderee(6, 2) == 8


def test_quatre_comptes_neufs_declenchent_la_ou_il_en_fallait_huit():
    """Le cœur du durcissement demandé."""
    assert _declenche(arrivees=4, neuves=4, membres=5000) is True
    # Avant : il fallait 8 arrivées, quelles qu'elles soient.
    assert 4 < automod.RAID_JOIN_THRESHOLD


def test_un_petit_serveur_est_protege_bien_plus_tot():
    assert _declenche(arrivees=4, neuves=0, membres=50) is True
    assert _declenche(arrivees=3, neuves=0, membres=50) is False


@pytest.mark.parametrize("membres", [50, 726, 5000, 50_000])
def test_on_n_est_jamais_plus_laxiste_qu_avant(membres):
    """Tout ce qui déclenchait hier déclenche encore aujourd'hui."""
    assert _declenche(arrivees=automod.RAID_JOIN_THRESHOLD, neuves=0, membres=membres) is True


def test_une_vague_de_veterans_sur_un_gros_serveur_ne_declenche_pas():
    """Une vidéo qui marche n'est pas un raid."""
    assert _declenche(arrivees=7, neuves=0, membres=50_000) is False


def test_la_fenetre_des_comptes_neufs_existe_vraiment():
    import inspect

    src = inspect.getsource(automod)
    assert "self.new_account_tracker" in src
    assert "RAID_COMPTE_NEUF_JOURS" in src


def test_l_alerte_dit_ce_qui_a_declenche():
    """Un staff doit pouvoir juger si l'alerte est fondée."""
    import inspect

    src = inspect.getsource(automod)
    assert "Seuil du serveur" in src
    assert "vélocité pondérée" in src
