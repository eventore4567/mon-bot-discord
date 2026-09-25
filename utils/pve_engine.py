"""Moteur de combat PvE partagé par ``+dragon`` et ``+zombie``.

Aucun import Discord ici : tout le calcul de combat est pur et se simule par
millions de tours en quelques secondes. C'est ce qui rend vérifiable la seule
promesse qui compte vraiment — qu'aucune stratégie triviale ne gagne presque
tout — et c'est impossible à mesurer si les règles vivent dans une ``View``.

Les deux jeux partagent l'ossature (``utils.game_ui.VuePvE``) et cette table de
résolution. Ils ne partagent pas leur contenu : l'un est un duel contre un
adversaire unique qui télégraphie ses coups, l'autre une survie par vagues où
la ressource rare est la munition et non les points de vie.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


# =============================================================================
# Source d'aléa
# =============================================================================

class Alea:
    """Interface minimale entre le moteur et sa source de hasard.

    La production injecte le tirage cryptographique de ``game_rewards`` — de
    l'argent réel est en jeu, un Mersenne Twister prévisible ne suffit pas. Les
    simulations injectent un ``random.Random`` graîné, sans quoi un combat raté
    serait irreproductible et donc indébogable.
    """

    def entier(self, bas: int, haut: int) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    def chance(self, probabilite: float) -> bool:
        """Vrai avec la probabilité donnée, au millième près."""
        if probabilite <= 0:
            return False
        if probabilite >= 1:
            return True
        return self.entier(1, 1000) <= round(probabilite * 1000)

    def choix(self, options):
        return options[self.entier(0, len(options) - 1)]

    def pondere(self, paires):
        """Tire une clé parmi ``[(clé, poids), …]``, poids entiers positifs."""
        total = sum(poids for _cle, poids in paires)
        tirage = self.entier(1, total)
        for cle, poids in paires:
            tirage -= poids
            if tirage <= 0:
                return cle
        return paires[-1][0]


class AleaPseudo(Alea):
    """Aléa graîné, réservé aux tests et aux simulations d'équilibrage."""

    def __init__(self, graine: int = 0):
        self._rng = random.Random(graine)

    def entier(self, bas: int, haut: int) -> int:
        return self._rng.randint(bas, haut)


class AleaSecurise(Alea):
    """Aléa de production, adossé à ``secrets`` via ``game_rewards``."""

    def entier(self, bas: int, haut: int) -> int:
        from utils import game_rewards

        return game_rewards.secure_randint(bas, haut)


# =============================================================================
# 🐉 DRAGON — duel au tour par tour contre un adversaire qui télégraphie
# =============================================================================

@dataclass(frozen=True)
class Dragon:
    cle: str
    nom: str
    emoji: str
    difficulte: str
    pv: int
    degats: int
    armure: int          # points retirés à chaque attaque physique
    esquive: float       # probabilité d'éviter une attaque ordinaire
    poids_souffle: int   # part de tours passés à souffler


DRAGONS: dict[str, Dragon] = {
    # Profils mesurés sur 8 000 combats par stratégie (tools/pve_balance_sweep.py).
    # La colonne qui compte est l'écart entre le meilleur réflexe simple et le jeu
    # informé : 31,6 % contre 96,1 % sur le dragonnet, 11,8 % contre 54,4 % sur
    # l'ombre. Changer un seul de ces nombres invalide la mesure.
    "dragonnet": Dragon("dragonnet", "Dragonnet", "🐲", "facile", 105, 15, 0, 0.05, 32),
    "feu": Dragon("feu", "Dragon de feu", "🔥", "normal", 110, 15, 2, 0.10, 34),
    "glace": Dragon("glace", "Dragon de glace", "🧊", "normal", 135, 13, 5, 0.06, 26),
    "ombre": Dragon("ombre", "Dragon d'ombre", "💀", "difficile", 125, 15, 3, 0.18, 36),
}

DIFFICULTES_DRAGON = ("facile", "normal", "difficile")

PV_JOUEUR = 100
TOURS_MAX_DRAGON = 18
SOINS_DRAGON = 2
SOIN_POINTS = 28
RAGE_MAX = 3

# Intentions du dragon. Elles sont tirées AVANT que le joueur ne choisisse et
# affichées : c'est l'information tactique qui rend le jeu autre chose qu'un
# bouton « attaquer » pressé en boucle.
GRIFFE, SOUFFLE, GARDE = "griffe", "souffle", "garde"

MULT_SOUFFLE = 2.3      # un souffle non paré coûte plus de deux tours de soin
MULT_GARDE = 0.35       # le dragon en garde frappe peu mais encaisse mal
REDUCTION_DEFENSE = 0.30   # ce qui passe encore quand le joueur pare
GARDE_ENCAISSE = 0.45      # dégâts reçus par le dragon pendant sa garde

DEGATS_ATTAQUE = (13, 19)
CHANCE_CRITIQUE = 0.15
MULT_CRITIQUE = 2.0
DEGATS_SPECIAL = (30, 40)

RAGE_PAR_ATTAQUE = 1      # une attaque qui touche échauffe aussi
RAGE_PAR_PARADE = 1
RAGE_PARADE_SOUFFLE = 2   # parer le souffle au bon tour, c'est la bonne lecture
TOURS_PAR_ENRAGEMENT = 4  # le dragon frappe +1 tous les quatre tours


def intentions_dragon(dragon: Dragon, alea: Alea, tours: int) -> list[str]:
    """Tire d'avance la suite complète des intentions du combat.

    Tirer l'intention après avoir vu le coup du joueur permettrait au dragon de
    souffler exactement quand le joueur n'a pas paré. Le combat entier est donc
    scellé à la création ; seule la prochaine intention est révélée.
    """
    restant = 100 - dragon.poids_souffle
    paires = [(SOUFFLE, dragon.poids_souffle), (GRIFFE, restant * 3 // 4), (GARDE, restant // 4)]
    suite = [alea.pondere(paires) for _ in range(tours + 1)]
    # Deux souffles consécutifs tuent presque à coup sûr un joueur qui a paré le
    # premier : il n'a plus de rage à dépenser et pare deux fois de suite sans
    # jamais frapper. On en casse la répétition.
    for index in range(1, len(suite)):
        if suite[index] == SOUFFLE and suite[index - 1] == SOUFFLE:
            suite[index] = GRIFFE
    return suite


def degats_joueur(dragon: Dragon, action: str, intention: str, alea: Alea) -> tuple[int, bool, bool]:
    """Dégâts infligés par le joueur. Retourne (dégâts, critique, esquivé)."""
    if action == "special":
        # La capacité spéciale ne se pare pas et ne s'esquive pas : c'est ce qui
        # paie les tours passés à parer au lieu de frapper.
        brut = alea.entier(*DEGATS_SPECIAL)
        return brut, False, False
    if action != "attaque":
        return 0, False, False
    if alea.chance(dragon.esquive):
        return 0, False, True
    brut = alea.entier(*DEGATS_ATTAQUE)
    critique = alea.chance(CHANCE_CRITIQUE)
    if critique:
        brut = int(brut * MULT_CRITIQUE)
    brut = max(1, brut - dragon.armure)
    if intention == GARDE:
        brut = max(1, int(brut * GARDE_ENCAISSE))
    return brut, critique, False


def degats_dragon(dragon: Dragon, action: str, intention: str, alea: Alea,
                  tour: int = 0) -> int:
    """Dégâts encaissés par le joueur, selon l'intention et sa réponse.

    ``tour`` enrage progressivement le dragon. Sans cela, un cycle « parer,
    parer, parer, capacité spéciale » encaisse presque rien pendant trois tours
    sur quatre et gagne à tous les coups : c'était la stratégie triviale
    mesurée à 99 % avant cet ajout.
    """
    brut = alea.entier(dragon.degats - 2, dragon.degats + 2) + tour // TOURS_PAR_ENRAGEMENT
    if intention == SOUFFLE:
        brut = int(brut * MULT_SOUFFLE)
    elif intention == GARDE:
        brut = int(brut * MULT_GARDE)
    if action == "defense":
        brut = int(brut * REDUCTION_DEFENSE)
    return max(0, brut)


ACTIONS_DRAGON = ("attaque", "defense", "soin", "special")


@dataclass
class EtatDragon:
    """État complet d'un duel, hors interface.

    Le même objet sert au combat réel et aux simulations d'équilibrage : une
    deuxième implémentation « pour les tests » ne mesurerait pas le vrai jeu.
    """

    dragon: Dragon
    alea: Alea
    pv_joueur: int = PV_JOUEUR
    pv_dragon: int = 0
    tour: int = 0
    rage: int = 0
    soins: int = SOINS_DRAGON
    intentions: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.pv_dragon:
            self.pv_dragon = self.dragon.pv
        if not self.intentions:
            self.intentions = intentions_dragon(self.dragon, self.alea, TOURS_MAX_DRAGON)

    @property
    def intention(self) -> str:
        return self.intentions[min(self.tour, len(self.intentions) - 1)]

    @property
    def intention_suivante(self) -> str:
        return self.intentions[min(self.tour + 1, len(self.intentions) - 1)]

    def actions_possibles(self) -> list[str]:
        actions = ["attaque", "defense"]
        if self.soins > 0:
            actions.append("soin")
        if self.rage >= RAGE_MAX:
            actions.append("special")
        return actions

    def jouer(self, action: str) -> dict:
        """Résout un tour complet et retourne son résumé.

        Le joueur frappe en premier : un dragon abattu ne riposte pas. Sans
        cela, le dernier coup gagnant coûterait encore un souffle et beaucoup de
        victoires se transformeraient en égalités incompréhensibles.
        """
        if action not in self.actions_possibles():
            raise ValueError(f"action indisponible : {action}")
        intention = self.intention
        inflige, critique, esquive = degats_joueur(self.dragon, action, intention, self.alea)
        self.pv_dragon = max(0, self.pv_dragon - inflige)

        soigne = 0
        if action == "soin":
            soigne = min(SOIN_POINTS, PV_JOUEUR - self.pv_joueur)
            self.pv_joueur += soigne
            self.soins -= 1
        elif action == "defense":
            # Parer une garde ne rapporte rien : le dragon ne frappe pas, il n'y
            # a rien à encaisser, et sans cette exception la parade en boucle
            # redevient la stratégie gagnante universelle.
            if intention == SOUFFLE:
                self.rage = min(RAGE_MAX, self.rage + RAGE_PARADE_SOUFFLE)
            elif intention == GRIFFE:
                self.rage = min(RAGE_MAX, self.rage + RAGE_PAR_PARADE)
        elif action == "special":
            self.rage = 0
        elif action == "attaque" and inflige > 0:
            self.rage = min(RAGE_MAX, self.rage + RAGE_PAR_ATTAQUE)

        recu = 0
        if self.pv_dragon > 0:
            recu = degats_dragon(self.dragon, action, intention, self.alea, self.tour)
            self.pv_joueur = max(0, self.pv_joueur - recu)

        self.tour += 1
        return {
            "action": action, "intention": intention, "inflige": inflige,
            "critique": critique, "esquive": esquive, "recu": recu, "soigne": soigne,
        }

    @property
    def fini(self) -> bool:
        return self.pv_joueur <= 0 or self.pv_dragon <= 0 or self.tour >= TOURS_MAX_DRAGON

    def issue(self) -> str:
        if self.pv_joueur <= 0 and self.pv_dragon <= 0:
            return "egalite"
        if self.pv_joueur <= 0:
            return "defaite"
        if self.pv_dragon <= 0:
            return "victoire"
        if self.tour >= TOURS_MAX_DRAGON:
            return "defaite"   # le dragon s'envole : pas de victoire aux points
        return "en_cours"


# =============================================================================
# 🧟 ZOMBIE — survie par vagues, la munition est la vraie ressource
# =============================================================================

@dataclass(frozen=True)
class Zombie:
    cle: str
    nom: str
    emoji: str
    pv: int
    degats: int
    coups: int = 1


ZOMBIES: dict[str, Zombie] = {
    "normal": Zombie("normal", "Marcheur", "🧟", 20, 7),
    "rapide": Zombie("rapide", "Coureur", "🏃", 12, 5, coups=2),
    "tank": Zombie("tank", "Colosse", "🛡️", 45, 11),
    "boss": Zombie("boss", "Alpha", "👹", 85, 17),
}

PV_SURVIVANT = 100
MUNITIONS_DEPART = 16
MUNITIONS_MAX = 30
COUT_TIR = 2
DEGATS_TIR = (24, 34)
CRITIQUE_TIR = 0.12
DEGATS_MELEE = (7, 12)
RISQUE_MELEE = 0.45          # part des corps-à-corps qui coûtent une morsure
MORSURE = (4, 9)
FOUILLE_MUNITIONS = (4, 7)
REDUCTION_BARRICADE = 0.30
BARRICADES = 3          # une ressource, pas un bouton « ne rien risquer »
SOIN_BARRICADE = 26     # se retrancher, c'est aussi se recoudre

# Chaque action doit avoir un rôle que les autres n'ont pas. Une barricade qui
# réduisait seulement les dégâts d'un tour ne servait à rien : le tour perdu
# coûtait plus cher que ce qu'elle épargnait, et « tirer sinon fouiller »
# battait toutes les stratégies réfléchies. En rendant des points de vie, elle
# devient la seule ressource de soin du jeu, et la décider au bon moment est ce
# qui sépare une partie jouée d'une partie subie.
VAGUES_MAX = 6          # atteignable, et atteinte : 1,2 % en jeu naïf, 76 % en jeu expert
TOURS_MAX_ZOMBIE = 40

ACTIONS_ZOMBIE = ("tirer", "melee", "barricader", "fouiller")


def composer_vague(numero: int) -> list[Zombie]:
    """Composition d'une vague. Déterministe : elle ne dépend que du numéro.

    Une composition tirée au hasard après avoir lu le choix du joueur serait
    invérifiable, et c'est exactement le reproche fait aux jeux truqués. Ici la
    vague n°7 est la même pour tout le monde, connue d'avance, et la difficulté
    vient de la ressource, pas d'une surprise.

    L'Alpha apparu à la vague 5 ne repart plus : une composition où le boss
    disparaît à la vague suivante rendrait la 6 plus facile que la 5, et la
    « difficulté croissante » ne serait vraie que sur le papier.
    """
    numero = max(1, int(numero))
    vague: list[Zombie] = []
    vague += [ZOMBIES["boss"]] * (numero // 5)
    vague += [ZOMBIES["normal"]] * (1 + (numero + 1) // 2)
    vague += [ZOMBIES["rapide"]] * (numero // 2)
    vague += [ZOMBIES["tank"]] * ((numero - 1) // 3 if numero >= 4 else 0)
    return vague


def pression_vague(numero: int) -> float:
    """Dégâts encaissés par tour face à une vague intacte.

    Séparée de ``degats_vague`` volontairement : la somme brute des dégâts de
    tous les zombies croît bien plus vite que ce qu'un survivant peut encaisser,
    et l'adosser directement rendait toute partie mortelle à la vague 4. Ici la
    pression monte, mais assez lentement pour que la munition — et non les
    points de vie — reste la ressource qui décide de la fin.
    """
    return 6.0 + 2.2 * max(1, int(numero))


def pv_vague(numero: int) -> int:
    return sum(z.pv for z in composer_vague(numero))


def degats_vague(numero: int) -> int:
    return sum(z.degats * z.coups for z in composer_vague(numero))


@dataclass
class EtatZombie:
    """Survie par vagues. Le même objet sert au jeu et aux simulations."""

    alea: Alea
    pv: int = PV_SURVIVANT
    munitions: int = MUNITIONS_DEPART
    vague: int = 1
    pv_vague_restants: int = 0
    tour: int = 0
    vagues_terminees: int = 0
    barricade: bool = False
    barricades_restantes: int = BARRICADES

    def __post_init__(self) -> None:
        if not self.pv_vague_restants:
            self.pv_vague_restants = pv_vague(self.vague)

    def actions_possibles(self) -> list[str]:
        actions = ["melee", "fouiller"]
        if self.barricades_restantes > 0:
            actions.append("barricader")
        if self.munitions >= COUT_TIR:
            actions.insert(0, "tirer")
        return actions

    def jouer(self, action: str) -> dict:
        if action not in self.actions_possibles():
            raise ValueError(f"action indisponible : {action}")
        inflige = 0
        critique = False
        trouve = 0
        soigne = 0
        morsure = False

        if action == "tirer":
            self.munitions -= COUT_TIR
            inflige = self.alea.entier(*DEGATS_TIR)
            critique = self.alea.chance(CRITIQUE_TIR)
            if critique:
                inflige *= 2
        elif action == "melee":
            inflige = self.alea.entier(*DEGATS_MELEE)
            morsure = self.alea.chance(RISQUE_MELEE)
        elif action == "fouiller":
            trouve = min(self.alea.entier(*FOUILLE_MUNITIONS), MUNITIONS_MAX - self.munitions)
            self.munitions += trouve
        elif action == "barricader":
            self.barricades_restantes -= 1
            soigne = min(SOIN_BARRICADE, PV_SURVIVANT - self.pv)
            self.pv += soigne

        self.pv_vague_restants = max(0, self.pv_vague_restants - inflige)
        self.barricade = action == "barricader"

        vague_nettoyee = self.pv_vague_restants <= 0
        recu = 0
        if not vague_nettoyee:
            # La riposte est proportionnelle à ce qu'il reste debout : une vague
            # presque nettoyée ne frappe pas comme une vague intacte.
            part = self.pv_vague_restants / max(1, pv_vague(self.vague))
            recu = max(1, int(pression_vague(self.vague) * part))
            if action == "barricader":
                recu = int(recu * REDUCTION_BARRICADE)
            if morsure:
                recu += self.alea.entier(*MORSURE)
            self.pv = max(0, self.pv - recu)
        elif morsure:
            recu = self.alea.entier(*MORSURE)
            self.pv = max(0, self.pv - recu)

        self.tour += 1
        if vague_nettoyee:
            self.vagues_terminees = self.vague
            if self.vague < VAGUES_MAX:
                self.vague += 1
                self.pv_vague_restants = pv_vague(self.vague)
                # Une vague nettoyée rend un peu de souffle, jamais assez pour
                # rendre la partie infinie.
                self.pv = min(PV_SURVIVANT, self.pv + 8)
                self.munitions = min(MUNITIONS_MAX, self.munitions + 4)

        return {
            "action": action, "inflige": inflige, "critique": critique,
            "recu": recu, "trouve": trouve, "soigne": soigne, "morsure": morsure,
            "vague_nettoyee": vague_nettoyee,
        }

    @property
    def fini(self) -> bool:
        return (
            self.pv <= 0
            or self.tour >= TOURS_MAX_ZOMBIE
            or self.vagues_terminees >= VAGUES_MAX
        )
