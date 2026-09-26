"""Les pages publiques secondaires partagent l'identité SentriX.

Avant le 2026-09-26, /start, /stats, /privacy, /terms et /media-kit avaient
un fond en dégradé CSS pendant que la landing recevait un canvas animé : deux
identités visuelles pour un même site, et une page d'erreur qui n'en avait
aucune. Elles passent toutes sur ``web.sentrix_fx_v1``.

Les pages légales sont aussi vérifiées sur le fond : Jayden a demandé qu'elles
ne contiennent « aucun faux texte juridique inventé », donc chaque affirmation
doit correspondre à ce que le projet fait réellement.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import MagicMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from web import marketing_growth_v40 as pages
from web import sentrix_fx_v1 as fx

PAGES = ("start_page", "stats_page", "privacy_page", "terms_page", "media_page")


def _rendre(nom: str) -> str:
    requete = MagicMock()
    requete.path = "/" + nom.replace("_page", "")
    requete.headers = {"Host": "exemple.test", "X-Forwarded-Proto": "https"}
    requete.scheme = "https"
    requete.host = "exemple.test"
    return asyncio.run(getattr(pages, nom)(requete)).text


@pytest.mark.parametrize("nom", PAGES)
def test_chaque_page_porte_le_fond_anime_partage(nom):
    corps = _rendre(nom)
    assert 'id="sxfx"' in corps, "le canvas partagé est absent"
    assert "requestAnimationFrame" in corps


@pytest.mark.parametrize("nom", PAGES)
def test_chaque_page_respecte_le_mouvement_reduit(nom):
    assert "prefers-reduced-motion" in _rendre(nom)


@pytest.mark.parametrize("nom", PAGES)
def test_chaque_page_arrete_l_animation_en_onglet_masque(nom):
    """Un fond animé dans un onglet qu'on ne regarde pas est du CPU brûlé."""
    assert "visibilitychange" in _rendre(nom)


@pytest.mark.parametrize("nom", PAGES)
def test_chaque_page_reste_lisible_sur_petit_ecran(nom):
    corps = _rendre(nom)
    assert "max-width:430px" in corps
    assert "max-width:360px" in corps


@pytest.mark.parametrize("nom", PAGES)
def test_le_focus_clavier_reste_visible(nom):
    assert ":focus-visible" in _rendre(nom)


def test_les_classes_des_corps_de_page_sont_conservees():
    """Renommer les classes aurait cassé cinq pages pour un gain nul.

    Chaque page n'utilise pas toutes les classes — /stats n'a pas de texte
    « muted », les pages légales n'ont ni « big » ni « status ». On vérifie
    donc les classes là où elles servent réellement, pas partout.
    """
    stats = _rendre("stats_page")
    for classe in ("card", "grid", "big", "status", "dot", "actions"):
        assert f'class="{classe}' in stats, f"{classe} absente de /stats"
    legal = _rendre("privacy_page")
    for classe in ("legal", "muted"):
        assert f'class="{classe}"' in legal, f"{classe} absente de /privacy"


def test_le_moteur_n_embarque_aucune_bibliotheque():
    """Three.js pour quatre couches de points serait des centaines de Ko."""
    assert "three" not in fx.JS.lower()
    assert "<script src=" not in fx.script()


# ------------------------------------------------------------------- légal

def test_la_confidentialite_dit_ou_les_donnees_vivent():
    corps = _rendre("privacy_page")
    for attendu in ("PostgreSQL", "Redis", "Railway", "sauvegardes"):
        assert attendu in corps, f"« {attendu} » manquant"


def test_la_confidentialite_couvre_ce_qui_a_ete_demande():
    corps = _rendre("privacy_page")
    for sujet in ("OAuth", "sanctions", "tickets", "niveaux", "Suppression",
                  "Sécurité", "contacter"):
        assert sujet in corps, f"section « {sujet} » manquante"


def test_les_conditions_couvrent_ce_qui_a_ete_demande():
    corps = _rendre("terms_page")
    for sujet in ("Responsabilité", "Disponibilité", "Limitation d’usage",
                  "Suspension", "Contact"):
        assert sujet in corps, f"section « {sujet} » manquante"


def test_les_pages_legales_renvoient_vers_une_route_reelle():
    """Ne jamais créer un bouton vers une route inexistante."""
    for nom in ("privacy_page", "terms_page"):
        assert 'href="/support"' in _rendre(nom)


def test_la_haute_disponibilite_est_decrite_sans_exagerer():
    """Deux instances, une seule active : c'est ce que fait réellement le lease."""
    corps = _rendre("privacy_page")
    assert "Deux instances" in corps
    assert "une seule traite les commandes" in corps


@pytest.mark.parametrize("nom", ("privacy_page", "terms_page"))
def test_les_pages_legales_sont_une_feuille_lisible(nom):
    """Le texte juridique se lit d'un trait, pas en vignettes.

    Avant ce test, ``.legal`` n'avait ni fond ni bordure ni padding : du texte
    nu posé sur le canvas animé, mesuré à ``backgroundColor: rgba(0,0,0,0)``
    dans le navigateur. Il reçoit une feuille unique et des titres ancrés.
    """
    corps = _rendre(nom)
    assert ".legal{border:1px solid" in corps or ".legal{max-width:870px;border:" in corps
    assert ".legal h2::before" in corps, "les titres n'ont pas d'ancre visuelle"


def test_la_feuille_legale_ne_refloute_pas_le_fond_a_chaque_frame():
    """Garde de performance demandée par Jayden.

    ``.card`` peut se permettre un ``backdrop-filter`` : ce sont de petites
    surfaces. La feuille légale fait ~870px de large sur toute la hauteur de
    la page ; la reflouter à chaque frame du canvas coûte cher pour un
    résultat identique sur un fond sombre.
    """
    corps = _rendre("privacy_page")
    debut = corps.index(".legal{")
    assert "backdrop-filter" not in corps[debut : corps.index("}", debut)]
