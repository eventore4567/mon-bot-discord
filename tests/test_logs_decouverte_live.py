"""La découverte de secours des salons de logs doit couvrir toutes les catégories.

Relevé en production le 2026-09-26 :

    V5 : aucun salon live reconnu guild=… type=channel_delete aliases=

La liste d'alias était vide. Cause : ``CHANNEL_ALIASES`` est indexée par
CATÉGORIE (« channels », « messages »…) alors que l'appelant transmet un type
d'évènement (« channel_delete »). La recherche sortait donc à vide, et
l'avertissement se déclenchait pour un cas qui n'était même pas une panne.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from cogs.live_log_delivery_v5 import CHANNEL_ALIASES, _aliases
from utils import log_service


def test_toutes_les_categories_ont_des_alias():
    """Une catégorie sans alias ne peut pas être découverte, et se signalait
    en avertissement à chaque évènement."""
    manquantes = sorted(set(log_service.CATEGORIES) - set(CHANNEL_ALIASES))
    assert manquantes == [], f"catégories sans salon à chercher : {manquantes}"


def test_aucun_alias_ne_vise_une_categorie_inexistante():
    inconnues = sorted(set(CHANNEL_ALIASES) - set(log_service.CATEGORIES))
    assert inconnues == []


@pytest.mark.parametrize("evenement,categorie", [
    ("channel_create", "channels"),
    ("channel_delete", "channels"),
    ("message_delete", "messages"),
    ("member_ban", "moderation"),
])
def test_un_type_d_evenement_est_resolu_vers_sa_categorie(evenement, categorie):
    """C'est la conversion qui manquait : sans elle, tout évènement dont le nom
    n'est pas déjà une catégorie donnait une liste vide."""
    assert log_service.category_for(evenement) == categorie
    assert _aliases(evenement), f"{evenement} ne résout toujours aucun salon"
    assert _aliases(evenement) == _aliases(categorie)


def test_les_alias_des_salons_correspondent_a_ceux_que_le_setup_cree():
    """Inventer des noms de salons rendrait la découverte inutile : ceux-ci
    viennent de setup_v2_completion."""
    reels = {"logs-messages", "logs-membres", "logs-salons", "logs-vocaux",
             "logs-tickets", "logs-ressources"}
    connus = {nom for noms in CHANNEL_ALIASES.values() for nom in noms}
    absents = sorted(n for n in reels if n not in connus)
    assert absents == [], f"le setup crée des salons que la découverte ignore : {absents}"


def test_une_categorie_sans_alias_ne_declenche_pas_d_avertissement():
    """Ne pas couvrir une catégorie n'est pas une panne. L'avertissement est
    réservé au cas où des noms existaient mais qu'aucun salon ne correspond."""
    import inspect

    from cogs import live_log_delivery_v5

    source = inspect.getsource(live_log_delivery_v5)
    bloc = source[source.index("no_live_channel_found"):]
    bloc = bloc[:bloc.index("return False")]
    assert "if alias:" in bloc, "l'avertissement n'est plus conditionné aux alias"
    assert "logger.debug" in bloc, "le cas non couvert doit rester en debug"
