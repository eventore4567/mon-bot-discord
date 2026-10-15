"""Combat entre membres (utils/pvp_engine.py) : règles exactes et équilibre mesuré.

Réglages choisis par simulation (15/10/2026) : bouclier 75 %, pouvoir 20-26.
Utiliser son pouvoir doit payer, anticiper celui de l'adversaire aussi, et
aucune stratégie triviale ne doit gagner presque à coup sûr.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from utils import pvp_engine as e  # noqa: E402
from utils.pve_engine import AleaPseudo  # noqa: E402


class Fixe(AleaPseudo):
    """Aléa figé : les dégâts valent toujours le bas de la fourchette, jamais de critique."""

    def entier(self, bas, haut):
        return 1000 if (bas, haut) == (1, 1000) else bas  # chance() : jamais


def nouveau():
    return e.Combat(e.Combattant(1, "Ana"), e.Combattant(2, "Bob"))


def test_tour_par_tour_degats_charge_et_bouclier():
    c = nouveau()
    coup = c.jouer(e.ATTAQUER, Fixe())
    assert (c.b.pv, c.a.charge, c.actif, coup.critique) == (90, 1, 1, False)
    c.jouer(e.BOUCLIER, Fixe())                 # Bob se protège
    assert c.b.bouclier and c.tour == 2
    coup = c.jouer(e.ATTAQUER, Fixe())          # 10 bruts, 75 % absorbés
    assert (coup.degats, coup.bloque, c.b.pv, c.b.bouclier) == (2, 8, 88, False)
    assert "absorbe 8 PV" in coup.texte


def test_le_pouvoir_exige_trois_charges_et_les_consomme():
    c = nouveau()
    with pytest.raises(ValueError):
        c.jouer(e.POUVOIR_SPECIAL, Fixe())
    for _ in range(3):
        c.jouer(e.ATTAQUER, Fixe())
        c.jouer(e.BOUCLIER, Fixe())
    assert c.a.peut_pouvoir
    coup = c.jouer(e.POUVOIR_SPECIAL, Fixe())
    assert c.a.charge == 0 and coup.degats > 0 and "pouvoir" in coup.texte


def test_fin_par_ko_ou_au_tour_maximum():
    c = nouveau()
    c.b.pv = 5
    c.jouer(e.ATTAQUER, Fixe())
    assert c.termine and c.vainqueur() is c.a
    with pytest.raises(ValueError):
        c.jouer(e.ATTAQUER, Fixe())
    c = nouveau()
    while not c.termine:
        c.jouer(e.BOUCLIER, Fixe())
    assert c.tour > e.TOURS_MAX and c.vainqueur() is None


def _taux(s1, s2, n=2000):
    gagnes = 0.0
    for i in range(n):
        c = nouveau()
        c.actif = i % 2
        alea = AleaPseudo(i)
        while not c.termine:
            c.jouer((s1 if c.actif == 0 else s2)(c), alea)
        v = c.vainqueur()
        gagnes += (v is c.a) + 0.5 * (v is None)
    return gagnes / n


def attaque(c):
    return e.ATTAQUER


def pouvoir(c):
    return e.POUVOIR_SPECIAL if c.joueur.peut_pouvoir else e.ATTAQUER


def anticipe(c):
    if c.joueur.peut_pouvoir and not c.adversaire.bouclier:
        return e.POUVOIR_SPECIAL
    if c.adversaire.peut_pouvoir and not c.joueur.bouclier:
        return e.BOUCLIER
    return e.ATTAQUER


def bouclier(c):
    return e.BOUCLIER


def test_equilibre_les_bons_choix_paient_sans_strategie_ecrasante():
    assert 0.60 < _taux(pouvoir, attaque) < 0.88, "utiliser son pouvoir doit payer, sans tout écraser"
    assert 0.55 < _taux(anticipe, pouvoir) < 0.85, "anticiper le pouvoir adverse doit payer"
    assert _taux(bouclier, attaque) < 0.05, "se protéger en boucle ne doit jamais gagner"
