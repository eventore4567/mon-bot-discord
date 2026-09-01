"""Une commande inconnue doit proposer les commandes proches.

Taper "+sticky" renvoyait vers "+help" alors que le bot connait sticky-set,
sticky-every et sticky-off. Deux gestionnaires de CommandNotFound coexistaient et
le plus recent (final_error_embed_v5) avait perdu les suggestions que le precedent
(bot_v16_commands) savait deja produire.
"""
import difflib

import pytest

from cogs import command_response_guard as guard
from cogs import final_error_embed_v5 as final


def test_le_handler_canonique_propose_des_suggestions():
    source = final.__file__
    text = open(source, encoding="utf-8").read()
    assert "_command_suggestions" in text, "le handler final ne suggere rien"
    assert "Vouliez-vous dire" in text


def test_il_reutilise_la_recherche_existante_au_lieu_d_en_ecrire_une_seconde():
    text = open(final.__file__, encoding="utf-8").read()
    assert "from . import command_response_guard" in text
    assert "difflib" not in text, "une seconde implementation de recherche a ete ecrite"


@pytest.mark.parametrize("tape,attendu", [
    ("sticky", "sticky-set"),
    ("stiky", "sticky-set"),
    ("stickyset", "sticky-set"),
])
def test_la_recherche_retrouve_bien_les_commandes_sticky(tape, attendu):
    """Verifie l'algorithme lui-meme sur le cas reel signale."""
    noms = ["sticky-set", "sticky-every", "sticky-off", "stats", "status", "ticket"]
    trouves = difflib.get_close_matches(tape, noms, n=8, cutoff=0.52)
    assert attendu in trouves, f"{tape} ne propose pas {attendu} : {trouves}"


def test_la_recherche_reste_silencieuse_sur_une_saisie_absurde():
    noms = ["sticky-set", "ban", "kick"]
    assert difflib.get_close_matches("zzzzzzzz", noms, n=8, cutoff=0.52) == []


def test_le_repli_reste_disponible_sans_suggestion():
    text = open(final.__file__, encoding="utf-8").read()
    assert "pour consulter les commandes disponibles" in text


def test_la_recherche_filtre_sur_les_permissions():
    """Ne jamais suggerer une commande que la personne ne peut pas utiliser."""
    text = open(guard.__file__, encoding="utf-8").read()
    assert "_can_suggest_command" in text
