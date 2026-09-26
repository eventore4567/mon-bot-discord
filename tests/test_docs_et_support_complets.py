"""La documentation et le support couvrent ce que SentriX fait réellement.

Les sujets listés ici ont été vérifiés contre les commandes réellement
chargées en production le 2026-09-26 (300 commandes, 38 catégories) et
contre les routes réellement déclarées. Aucune affirmation n'est inventée.
"""
from __future__ import annotations

import os
import re
from unittest.mock import MagicMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from web.public_docs_v1 import render as rendre_docs
from web.public_support_v2 import render as rendre_support


def _requete(chemin: str) -> MagicMock:
    r = MagicMock()
    r.path, r.scheme, r.host = chemin, "https", "exemple.test"
    r.headers = {"Host": "exemple.test"}
    r.query = {}
    return r


def _dashboard() -> MagicMock:
    d = MagicMock()
    d._public_url.return_value = "https://exemple.test"
    return d


def _docs() -> str:
    return rendre_docs(_requete("/docs"), _dashboard())


def _support() -> str:
    return rendre_support(_requete("/support"), _dashboard(), "")


# --- documentation ---------------------------------------------------------

@pytest.mark.parametrize("ancre", [
    "installation", "discord", "dashboard", "moderation", "security", "tickets",
    "logs", "roles", "welcome", "levels", "economy", "games", "music",
    "notifications", "automation", "ai", "troubleshooting",
    "commandes", "permissions", "faq", "support",
])
def test_la_documentation_couvre_chaque_domaine(ancre):
    corps = _docs()
    assert f'id="{ancre}"' in corps, f"section #{ancre} absente"
    assert f'href="#{ancre}"' in corps, f"#{ancre} absent de la barre latérale"


def test_la_documentation_garde_sa_recherche():
    assert 'id="docSearch"' in _docs()


def test_la_documentation_ne_cite_que_des_commandes_reelles():
    """Les commandes nommées dans la doc existent vraiment sur le bot.

    Relevé sur la production : +setprefix (Configuration), +help (Autres),
    +permissions (PermissionsExplain), +panic (SecurityHardening) et
    +setup (SentriXSetup).
    """
    corps = _docs()
    citees = set(re.findall(r"<code>\+([a-z][a-z0-9-]*)</code>", corps))
    connues = {"setprefix", "help", "permissions", "panic", "setup"}
    assert citees <= connues, f"commandes non vérifiées citées : {sorted(citees - connues)}"


def test_la_documentation_pointe_vers_des_routes_existantes():
    corps = _docs()
    for lien in ('href="/commands"', 'href="/support"', 'href="/app"'):
        assert lien in corps


# --- support ---------------------------------------------------------------

@pytest.mark.parametrize("cle", ["commands", "dashboard", "permissions", "security", "offline", "logs"])
def test_le_support_couvre_chaque_panne_frequente(cle):
    corps = _support()
    assert f'data-key="{cle}"' in corps, f"sujet {cle} absent des boutons"
    assert f" {cle}:{{title:" in corps, f"contenu du sujet {cle} absent"


def test_le_support_a_une_recherche_accessible():
    corps = _support()
    assert 'id="supportSearch"' in corps
    assert 'aria-live="polite"' in corps, "le nombre de résultats n'est pas annoncé"
    assert "sx-sr-only" in corps, "le champ de recherche n'a pas de label"
    assert ":focus-visible" in corps


def test_le_support_garde_le_rapport_copiable():
    corps = _support()
    assert "navigator.clipboard" in corps
    assert "<textarea" in corps


def test_le_support_decrit_la_haute_disponibilite_sans_inventer():
    """Deux instances dont une seule sert : c'est le fonctionnement réel."""
    corps = _support()
    assert "deux instances" in corps
    assert "une seule sert" in corps


# --- les deux --------------------------------------------------------------

@pytest.mark.parametrize("rendu", [_docs, _support])
def test_aucune_page_ne_reecrit_son_interface_en_boucle(rendu):
    """Contrainte de Jayden : aucun intervalle qui réécrit l'interface."""
    corps = rendu()
    scripts = " ".join(re.findall(r"<script>(.*?)</script>", corps, re.S))
    assert "setInterval" not in scripts


@pytest.mark.parametrize("rendu", [_docs, _support])
def test_chaque_page_respecte_le_mouvement_reduit(rendu):
    assert "prefers-reduced-motion" in rendu()
