"""Les tirages qui décident d'un gain ne passent plus par ``random``.

**Ce qui était mesuré.** ``utils/game_rewards`` avait déjà tranché pour
``secrets`` et exposait ``secure_pick``, ``secure_sample``,
``secure_randint`` — mais dix-neuf sites des jeux étaient restés sur
``random``, et pas les moins importants :

    games_economy  random.random() >= chance    décidait gain ou perte
    games_economy  random.randint(30, 70)       fixait le MONTANT du gain
    games_economy  random.shuffle(letters)      l'anagramme d'une course dotée
    games_economy  random.shuffle(options)      la position de la bonne réponse
    games_economy  random.uniform(2.0, 6.0)     le départ d'un duel de réflexe
    minigames      random.choice(options)       le coup du bot contre le joueur
    minigames      random.randint(1, 100)       le nombre à deviner
    minigames      random.shuffle(paquet)       l'ordre de tout un paquet

``random`` est le Mersenne Twister, et c'est une instance **globale** partagée
par tous les jeux du processus : toutes ces manches puisaient dans une seule et
même suite, celle qu'un joueur peut observer ailleurs dans le bot.

**La façon de tester compte ici.** Un test qui cherche ``random.`` dans le
source casserait au premier commentaire qui mentionne le mot — et ce fichier-là
en contient. On mesure donc deux choses réelles : la distribution des
primitives, et le fait que les jeux continuent de fonctionner quand on rend
``random`` inutilisable.
"""
from __future__ import annotations

import os
from collections import Counter

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from utils import game_rewards


# =============================================================================
# secure_chance : la distribution doit être celle annoncée
# =============================================================================

#: Assez d'échantillons pour que l'écart-type d'une proportion soit sous 0,2 %,
#: donc qu'une tolérance de 1 % ne produise pas d'échec intermittent.
TIRAGES = 60_000
TOLERANCE = 0.01


@pytest.mark.parametrize("probabilite", [0.15, 0.30, 0.50, 0.70, 0.85, 0.95])
def test_secure_chance_respecte_la_probabilite(probabilite):
    """Si la distribution dérivait, l'équilibre de tous les jeux changerait
    sans que personne ne s'en aperçoive — c'est le risque réel d'un
    remplacement de source aléatoire."""
    vrais = sum(game_rewards.secure_chance(probabilite) for _ in range(TIRAGES))
    observe = vrais / TIRAGES
    assert abs(observe - probabilite) < TOLERANCE, (
        f"p={probabilite} donne {observe:.4f}"
    )


def test_secure_chance_aux_bornes_est_deterministe():
    assert all(not game_rewards.secure_chance(0.0) for _ in range(500))
    assert all(game_rewards.secure_chance(1.0) for _ in range(500))


def test_secure_chance_ramene_une_probabilite_absurde_dans_les_bornes():
    """Mieux vaut une manche jouable qu'une exception au milieu d'une partie
    où la mise est déjà débitée."""
    assert game_rewards.secure_chance(-5) is False
    assert game_rewards.secure_chance(42) is True


def test_secure_chance_ne_rend_pas_toujours_la_meme_chose():
    """Garde-fou : une implémentation cassée qui rendrait une constante
    passerait tous les tests de borne ci-dessus."""
    tirages = [game_rewards.secure_chance(0.5) for _ in range(200)]
    assert True in tirages and False in tirages


# =============================================================================
# secure_shuffle : uniforme, et sans effet de bord
# =============================================================================

def test_secure_shuffle_ne_touche_pas_a_loriginal():
    """La différence avec ``random.shuffle``, qui mélange en place. Un appelant
    qui garde le mot d'origine comme RÉPONSE et la liste mélangée comme
    anagramme ne doit pas voir l'un réécrire l'autre."""
    original = ["a", "b", "c", "d", "e"]
    copie_attendue = list(original)
    melange = game_rewards.secure_shuffle(original)
    assert original == copie_attendue
    assert sorted(melange) == copie_attendue
    assert melange is not original


def test_secure_shuffle_accepte_nimporte_quel_iterable():
    """Appelé sur une chaîne (les lettres d'un mot) et sur une vue de
    dictionnaire (les couleurs d'un quiz)."""
    assert sorted(game_rewards.secure_shuffle("chat")) == ["a", "c", "h", "t"]
    assert len(game_rewards.secure_shuffle({"a": 1, "b": 2}.items())) == 2


def test_secure_shuffle_donne_une_permutation_uniforme():
    """Fisher-Yates à l'envers est la seule forme qui la donne. Tirer un indice
    au hasard pour chaque position produit un biais mesurable, et sur une
    anagramme cela veut dire que certaines lettres restent trop souvent en
    place."""
    compte = Counter(tuple(game_rewards.secure_shuffle([1, 2, 3])) for _ in range(60_000))
    assert len(compte) == 6, f"permutations manquantes : {sorted(compte)}"
    attendu = 60_000 / 6
    for permutation, vu in compte.items():
        assert abs(vu - attendu) < attendu * 0.15, f"{permutation} : {vu} pour ~{attendu:.0f}"


def test_secure_shuffle_sur_une_liste_vide_ou_dun_element():
    assert game_rewards.secure_shuffle([]) == []
    assert game_rewards.secure_shuffle(["seul"]) == ["seul"]


# =============================================================================
# secure_delay : le départ d'un jeu de réflexe
# =============================================================================

def test_secure_delay_reste_dans_lintervalle():
    for _ in range(3_000):
        d = game_rewards.secure_delay(1.8, 4.2)
        assert 1.8 <= d <= 4.2


def test_secure_delay_couvre_vraiment_lintervalle():
    """Un délai qui tomberait toujours au même endroit rendrait le jeu de
    réflexe pré-calibrable — exactement ce que la conversion corrige."""
    valeurs = {game_rewards.secure_delay(2.0, 6.0) for _ in range(2_000)}
    assert len(valeurs) > 500, "le délai ne varie presque pas"
    assert min(valeurs) < 2.5 and max(valeurs) > 5.5, "l'intervalle n'est pas couvert"


def test_secure_delay_avec_des_bornes_inversees_ne_leve_pas():
    assert game_rewards.secure_delay(5.0, 1.0) == 5.0
    assert game_rewards.secure_delay(-3.0, -1.0) == 0.0


# =============================================================================
# La preuve comportementale : les jeux ne dépendent plus de `random`
# =============================================================================

def test_les_primitives_sures_nutilisent_pas_le_module_random(monkeypatch):
    """On rend ``random`` inutilisable, puis on appelle les primitives.

    C'est la mesure qui compte, et elle ne peut pas se tromper comme le ferait
    une recherche de texte : si une primitive puisait encore dans la suite
    globale, elle lèverait ici.
    """
    import random as module_random

    def refuser(*a, **k):
        raise AssertionError("un tirage de jeu est passé par random")

    for nom in ("random", "randint", "choice", "shuffle", "uniform", "sample"):
        monkeypatch.setattr(module_random, nom, refuser)

    assert game_rewards.secure_chance(0.5) in (True, False)
    assert game_rewards.secure_randint(1, 10) in range(1, 11)
    assert sorted(game_rewards.secure_shuffle([1, 2, 3])) == [1, 2, 3]
    assert 1.0 <= game_rewards.secure_delay(1.0, 2.0) <= 2.0
    assert game_rewards.secure_pick(["a", "b"]) in ("a", "b")
    assert len(game_rewards.secure_sample(range(10), 3)) == 3


def test_le_tirage_de_butin_ne_passe_pas_par_random(monkeypatch):
    """``tirer_butin`` décide d'une rareté, donc d'un gain."""
    import random as module_random

    from cogs.games_economy import tirer_butin

    def refuser(*a, **k):
        raise AssertionError("le tirage de butin est passé par random")

    for nom in ("random", "randint", "choice", "shuffle", "uniform", "sample"):
        monkeypatch.setattr(module_random, nom, refuser)

    for _ in range(300):
        tirer_butin("fishing")  # ne doit pas lever


def test_la_grille_de_choix_ne_passe_pas_par_random(monkeypatch):
    """``_reaction_round`` place la bonne réponse parmi les leurres :
    connaître sa position, c'est gagner."""
    import random as module_random

    from cogs import games_economy

    constructeur = getattr(games_economy, "_reaction_round", None)
    if constructeur is None:
        pytest.skip("la fabrique de manche de réaction a été renommée")

    def refuser(*a, **k):
        raise AssertionError("la grille de choix est passée par random")

    for nom in ("random", "randint", "choice", "shuffle", "uniform", "sample"):
        monkeypatch.setattr(module_random, nom, refuser)

    for _ in range(100):
        options, cible = constructeur()
        assert cible in options


# =============================================================================
# L'équilibre des jeux n'a pas bougé
# =============================================================================

def test_le_montant_de_base_dune_expedition_garde_sa_plage():
    """La conversion de ``random.randint(30, 70)`` vers ``secure_randint`` doit
    donner exactement la même plage — sinon tous les gains du bot changent
    silencieusement."""
    valeurs = [game_rewards.secure_randint(30, 70) for _ in range(20_000)]
    assert min(valeurs) == 30 and max(valeurs) == 70
    moyenne = sum(valeurs) / len(valeurs)
    assert abs(moyenne - 50.0) < 0.6, f"moyenne {moyenne:.2f}, attendu ~50"


def test_secure_randint_couvre_toutes_les_valeurs():
    vus = Counter(game_rewards.secure_randint(1, 6) for _ in range(30_000))
    assert sorted(vus) == [1, 2, 3, 4, 5, 6]
    attendu = 30_000 / 6
    for face, compte in vus.items():
        assert abs(compte - attendu) < attendu * 0.12, f"face {face} : {compte}"
