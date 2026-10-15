"""Moteur du combat entre deux membres (``+fight``), sans Discord.

Pur et simulable, comme ``utils/pve_engine.py`` : l'équilibre se vérifie sur des
milliers de combats (tests/test_pvp_engine.py) — aucune stratégie triviale
(toujours attaquer, toujours se protéger) ne doit gagner presque à coup sûr.

Règles, une phrase chacune :
* chacun commence à 100 PV ; on joue chacun son tour ;
* Attaque : 10 à 16 dégâts, 15 % de coup critique (×1,5) ;
* Bouclier : le prochain coup reçu est réduit de 75 % ; donne aussi une charge ;
* chaque tour joué ajoute une charge (3 au maximum) ;
* Pouvoir spécial : coûte 3 charges, 20 à 26 dégâts ;
* deux boucliers de suite ne se cumulent pas ;
* 30 tours au plus : ensuite, le plus de PV restants l'emporte.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from utils.pve_engine import Alea

PV_DEPART = 100
ATTAQUE = (10, 16)
CRITIQUE = 0.15
POUVOIR = (20, 26)
CHARGE_POUVOIR = 3
REDUCTION_BOUCLIER = 0.75
TOURS_MAX = 30

ATTAQUER, BOUCLIER, POUVOIR_SPECIAL = "attaque", "bouclier", "pouvoir"


@dataclass
class Combattant:
    user_id: int
    nom: str
    pv: int = PV_DEPART
    bouclier: bool = False
    charge: int = 0

    @property
    def peut_pouvoir(self) -> bool:
        return self.charge >= CHARGE_POUVOIR


@dataclass
class Coup:
    acteur: str
    cible: str
    action: str
    degats: int = 0
    critique: bool = False
    bloque: int = 0          # dégâts absorbés par le bouclier
    texte: str = ""


@dataclass
class Combat:
    a: Combattant
    b: Combattant
    tour: int = 1
    actif: int = 0           # 0 : a joue, 1 : b joue
    historique: list[Coup] = field(default_factory=list)

    @property
    def joueur(self) -> Combattant:
        return self.a if self.actif == 0 else self.b

    @property
    def adversaire(self) -> Combattant:
        return self.b if self.actif == 0 else self.a

    @property
    def termine(self) -> bool:
        return self.a.pv <= 0 or self.b.pv <= 0 or self.tour > TOURS_MAX

    def vainqueur(self) -> Combattant | None:
        """Le gagnant, ou None en cas d'égalité (combat terminé seulement)."""
        if self.a.pv <= 0 < self.b.pv:
            return self.b
        if self.b.pv <= 0 < self.a.pv:
            return self.a
        if self.a.pv == self.b.pv:
            return None
        return self.a if self.a.pv > self.b.pv else self.b

    def jouer(self, action: str, alea: Alea) -> Coup:
        if self.termine:
            raise ValueError("Le combat est terminé.")
        joueur, cible = self.joueur, self.adversaire
        if action == POUVOIR_SPECIAL and not joueur.peut_pouvoir:
            raise ValueError("Pouvoir pas encore chargé.")
        coup = Coup(acteur=joueur.nom, cible=cible.nom, action=action)

        if action == BOUCLIER:
            joueur.bouclier = True
            joueur.charge = min(CHARGE_POUVOIR, joueur.charge + 1)
            coup.texte = f"🛡️ {joueur.nom} lève son bouclier."
        else:
            if action == POUVOIR_SPECIAL:
                brut = alea.entier(*POUVOIR)
                joueur.charge = 0
            else:
                brut = alea.entier(*ATTAQUE)
                if alea.chance(CRITIQUE):
                    brut = round(brut * 1.5)
                    coup.critique = True
                joueur.charge = min(CHARGE_POUVOIR, joueur.charge + 1)
            degats = brut
            if cible.bouclier:
                coup.bloque = round(brut * REDUCTION_BOUCLIER)
                degats = brut - coup.bloque
                cible.bouclier = False
            cible.pv = max(0, cible.pv - degats)
            coup.degats = degats
            if action == POUVOIR_SPECIAL:
                coup.texte = f"✨ {joueur.nom} déchaîne son pouvoir : **-{degats} PV** à {cible.nom}."
            else:
                coup.texte = (
                    f"⚔️ {joueur.nom} frappe {cible.nom} : **-{degats} PV**"
                    + (" — coup critique !" if coup.critique else ".")
                )
            if coup.bloque:
                coup.texte += f" Le bouclier absorbe {coup.bloque} PV."
        self.historique.append(coup)
        self.actif = 1 - self.actif
        if self.actif == 0:
            self.tour += 1
        return coup


def barre(pv: int, longueur: int = 10) -> str:
    plein = max(0, min(longueur, round(pv / PV_DEPART * longueur)))
    return "█" * plein + "░" * (longueur - plein)


__all__ = [
    "Combat", "Combattant", "Coup", "barre", "ATTAQUER", "BOUCLIER", "POUVOIR_SPECIAL",
    "PV_DEPART", "TOURS_MAX", "CHARGE_POUVOIR",
]
