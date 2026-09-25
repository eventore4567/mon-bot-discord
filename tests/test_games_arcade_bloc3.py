"""Bloc 3 — +dragon, +zombie, +ice, +potion : composants et fin de manche.

Le moteur est testé ailleurs (test_pve_engine, test_ice_puzzle, test_crafting).
Ici on vérifie ce que Discord reçoit vraiment : aucun bouton vide, aucun
identifiant qui trahisse la solution, aucune récompense versée deux fois, et des
composants qui disparaissent quand l'action devient impossible.
"""
from __future__ import annotations

import asyncio
import inspect
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
import pytest

from cogs import games_arcade as arcade
from services import crafting
from utils import ice_puzzle as ice
from utils import pve_engine as pve
from utils.game_ui import VuePvE, composants_invisibles, valider_composants
from utils.pve_engine import AleaPseudo


def _cog():
    return SimpleNamespace(bot=None, emoji_monnaie="🪙",
                           ligne_recompense=lambda r: "", rendre=None)


def _ctx():
    return SimpleNamespace(guild=SimpleNamespace(id=1), author=SimpleNamespace(id=2),
                           channel=SimpleNamespace(id=3))


def _boutons(vue):
    return [e for e in vue.children if isinstance(e, discord.ui.Button)]


def _vue_dragon(cle="feu"):
    return arcade._VueDragon(_cog(), _ctx(), pve.DRAGONS[cle], "sid-dragon")


def _vue_zombie():
    return arcade._VueZombie(_cog(), _ctx(), "sid-zombie")


def _vue_ice(graine=1):
    return arcade._VueIce(_cog(), _ctx(), ice.generer(AleaPseudo(graine)), "sid-ice")


def _vue_potion(stocks=None):
    return arcade._VuePotion(_cog(), _ctx(), stocks or {}, "sid-potion")


TOUTES = ("dragon", "zombie", "ice", "potion")


def _vue(nom):
    return {"dragon": _vue_dragon, "zombie": _vue_zombie,
            "ice": _vue_ice, "potion": _vue_potion}[nom]()


# =============================================================================
# Composants — la règle que « Course à l'emoji » avait violée
# =============================================================================

@pytest.mark.parametrize("nom", TOUTES)
def test_aucun_bouton_vide(nom):
    vue = _vue(nom)
    valider_composants(vue)
    assert composants_invisibles(vue) == []
    assert _boutons(vue), "une manche sans aucun bouton est injouable"


@pytest.mark.parametrize("nom", TOUTES)
def test_les_identifiants_sont_uniques(nom):
    ids = [b.custom_id for b in _boutons(_vue(nom))]
    assert len(ids) == len(set(ids))
    assert all(ids), "un bouton sans custom_id ne peut pas être routé"


@pytest.mark.parametrize("nom", TOUTES)
def test_les_identifiants_sont_prefixes_par_leur_jeu(nom):
    for bouton in _boutons(_vue(nom)):
        assert bouton.custom_id.startswith(f"{nom}:"), bouton.custom_id


@pytest.mark.parametrize("nom", TOUTES)
def test_la_manche_tient_dans_les_cinq_rangees_de_discord(nom):
    rangees = {b.row for b in _boutons(_vue(nom)) if b.row is not None}
    assert not rangees or max(rangees) <= 4
    assert len(_boutons(_vue(nom))) <= 25


@pytest.mark.parametrize("nom", TOUTES)
def test_chaque_jeu_offre_une_sortie_propre(nom):
    ids = [b.custom_id for b in _boutons(_vue(nom))]
    assert f"{nom}:abandon" in ids, "aucun moyen de quitter la manche"


def test_aucun_identifiant_ne_trahit_le_secret_du_niveau():
    """Le chemin gagnant doit rester côté serveur. Un custom_id directionnel
    est neutre ; il ne dit pas laquelle des quatre flèches résout la grille."""
    vue = _vue_ice()
    ids = " ".join(b.custom_id for b in _boutons(vue))
    for direction in vue.niveau.solution:
        assert f"ice:solution" not in ids
    assert sorted(b.custom_id for b in _boutons(vue)) == [
        "ice:abandon", "ice:bas", "ice:droite", "ice:gauche", "ice:haut"]
    # Les quatre flèches existent toujours, y compris celles qui sont bloquées :
    # n'afficher que les directions utiles révélerait la solution.
    assert len([b for b in _boutons(vue) if b.custom_id != "ice:abandon"]) == 4


def test_les_boutons_du_dragon_suivent_ce_qui_est_reellement_jouable():
    """Un bouton « Déchaîner » sans rage serait cliquable pour rien."""
    vue = _vue_dragon()
    ids = {b.custom_id for b in _boutons(vue)}
    assert "dragon:special" not in ids and "dragon:attaque" in ids
    vue.etat.rage = pve.RAGE_MAX
    vue._reconstruire()
    assert "dragon:special" in {b.custom_id for b in _boutons(vue)}
    vue.etat.soins = 0
    vue._reconstruire()
    assert "dragon:soin" not in {b.custom_id for b in _boutons(vue)}


def test_les_boutons_du_zombie_suivent_les_munitions_et_les_retranchements():
    vue = _vue_zombie()
    assert "zombie:tirer" in {b.custom_id for b in _boutons(vue)}
    vue.etat.munitions = 0
    vue.etat.barricades_restantes = 0
    vue._reconstruire()
    ids = {b.custom_id for b in _boutons(vue)}
    assert "zombie:tirer" not in ids and "zombie:barricader" not in ids
    assert "zombie:melee" in ids and "zombie:fouiller" in ids


def test_l_atelier_n_affiche_que_les_recettes_realisables():
    assert not [b for b in _boutons(_vue_potion()) if "craft" in b.custom_id]
    vue = _vue_potion({"herbe": 2, "rosee": 1})
    ids = {b.custom_id for b in _boutons(vue)}
    assert "potion:craft:vigueur" in ids
    assert "potion:craft:fortune" not in ids


def test_l_atelier_n_affiche_boire_que_si_la_potion_existe():
    assert not [b for b in _boutons(_vue_potion()) if "drink" in b.custom_id]
    vue = _vue_potion({"savoir": 2})
    assert "potion:drink:savoir" in {b.custom_id for b in _boutons(vue)}


def test_la_recolte_disparait_une_fois_utilisee():
    """Un bouton qui refuse systématiquement vaut mieux absent."""
    vue = _vue_potion()
    assert "potion:recolte" in {b.custom_id for b in _boutons(vue)}
    vue.recolte_utilisee = True
    vue._reconstruire()
    assert "potion:recolte" not in {b.custom_id for b in _boutons(vue)}


@pytest.mark.parametrize("nom", ("dragon", "zombie"))
def test_plus_aucun_bouton_apres_la_fin_du_combat(nom):
    vue = _vue(nom)
    if nom == "dragon":
        vue.etat.pv_dragon = 0
    else:
        vue.etat.pv = 0
    vue._reconstruire()
    assert _boutons(vue) == []


# =============================================================================
# Socle PvE
# =============================================================================

def test_le_socle_ne_tient_aucun_point_de_vie():
    """Deux compteurs de PV finiraient par se contredire, et l'affichage
    mentirait sans que rien ne plante."""
    champs = set(inspect.signature(VuePvE.__init__).parameters)
    assert "pv_joueur" not in champs and "pv_ennemi" not in champs
    vue = _vue_dragon()
    assert not hasattr(vue, "pv_joueur")
    assert vue.tour == vue.etat.tour


def test_la_barre_de_vie_garde_un_bloc_pour_un_survivant():
    """Arrondir un point de vie restant à zéro afficherait un mort qui joue."""
    assert VuePvE.barre(0, 100) == "░" * 10
    assert VuePvE.barre(1, 100).startswith("█")
    assert VuePvE.barre(100, 100) == "█" * 10
    assert len(VuePvE.barre(37, 100)) == 10
    assert VuePvE.barre(50, 0), "un maximum nul ne doit pas diviser par zéro"


@pytest.mark.parametrize("nom", ("dragon", "zombie"))
def test_la_recompense_n_est_marquee_qu_une_fois(nom):
    vue = _vue(nom)
    assert vue.marquer_recompense_versee() is True
    assert vue.marquer_recompense_versee() is False


@pytest.mark.parametrize("nom", ("dragon", "zombie"))
def test_l_abandon_termine_la_manche(nom):
    vue = _vue(nom)
    vue.abandonner()
    assert vue.abandonne and vue.combat_fini and vue.terminee


def test_le_journal_ne_garde_que_les_derniers_tours():
    vue = _vue_dragon()
    for index in range(10):
        vue.noter(f"tour {index}")
    assert len(vue.journal) == 3
    assert vue.journal[-1] == "tour 9"


def test_les_deux_jeux_pve_partagent_le_meme_socle():
    """Deux moteurs séparés dériveraient au premier correctif appliqué d'un
    seul côté."""
    assert issubclass(arcade._VueDragon, VuePvE)
    assert issubclass(arcade._VueZombie, VuePvE)
    for methode in ("marquer_recompense_versee", "abandonner", "barre", "noter"):
        assert getattr(arcade._VueDragon, methode) is getattr(VuePvE, methode)
        assert getattr(arcade._VueZombie, methode) is getattr(VuePvE, methode)


def test_le_bouton_abandon_est_lui_aussi_partage():
    assert arcade._BoutonAbandon("dragon").custom_id == "dragon:abandon"
    assert arcade._BoutonAbandon("zombie").custom_id == "zombie:abandon"
    for classe in (arcade._VueDragon, arcade._VueZombie, arcade._VueIce, arcade._VuePotion):
        assert hasattr(classe, "abandonner_manche"), classe.__name__


# =============================================================================
# Rendu
# =============================================================================

def test_le_texte_du_dragon_montre_les_deux_barres_et_l_intention():
    texte = _vue_dragon().texte()
    assert texte.count("█") + texte.count("░") >= 20, "il manque une barre de vie"
    assert any(picto in texte for picto, _ in arcade.LIBELLES_INTENTION.values())
    assert "Rage" in texte and "tour **1/" in texte


def test_le_texte_du_zombie_montre_la_horde_et_les_ressources():
    texte = _vue_zombie().texte()
    assert "Vague 1/" in texte
    assert all(mot in texte for mot in ("Munitions", "retranchements"))
    for zombie in pve.composer_vague(1):
        assert zombie.emoji in texte


def test_le_texte_du_lac_ne_montre_jamais_la_solution():
    vue = _vue_ice()
    texte = vue.texte()
    for direction in set(vue.niveau.solution):
        assert direction not in texte.lower(), f"« {direction} » est écrit en clair"
    assert ice.PINGOUIN in texte and ice.TROU in texte


def test_le_lac_revele_la_solution_seulement_apres_la_defaite():
    vue = _vue_ice()
    vue.coups = vue.niveau.coups_max
    vue.terminer()
    texte = vue.texte()
    assert all(ice.FLECHES[d] in texte for d in vue.niveau.solution)


def test_l_atelier_liste_ce_qui_manque_recette_par_recette():
    texte = _vue_potion({"herbe": 1}).texte()
    for recette in crafting.RECETTES.values():
        assert recette.nom in texte
    assert "manque" in texte


# =============================================================================
# Anti-double-clic
# =============================================================================

@pytest.mark.parametrize("nom", TOUTES)
def test_deux_clics_simultanes_n_en_valent_qu_un(nom):
    vue = _vue(nom)
    appels: list[int] = []

    async def lent():
        await asyncio.sleep(0.03)
        appels.append(1)

    async def scenario():
        return await asyncio.gather(vue.jouer_un_coup(lent), vue.jouer_un_coup(lent))

    resultats = asyncio.run(scenario())
    assert appels == [1]
    assert sorted(resultats) == [False, True]


@pytest.mark.parametrize("nom", TOUTES)
def test_un_intrus_ne_peut_pas_jouer_la_manche_d_un_autre(nom):
    vue = _vue(nom)
    assert vue.proprietaire_id == 2
    assert vue.message_intrus and "quelqu'un d'autre" in vue.message_intrus
