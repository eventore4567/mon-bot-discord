"""utils/command_refs.py : une commande citée dans un texte doit exister là où le membre la tape.

Avant le 22/10/2026, en « / », les textes affichaient /jeuxjour, /infinit resume ou
/trivia : des commandes absentes du menu.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import command_refs  # noqa: E402

SLASH = SimpleNamespace(interaction=object(), clean_prefix="/")
PREFIXE = SimpleNamespace(interaction=None, clean_prefix="+")


def test_en_slash_le_chemin_publie():
    assert command_refs.reference(SLASH, "dailygames", nom_prefixe="jeuxjour") == "/games today"
    assert command_refs.reference(SLASH, "trivia") == "/play trivia"
    assert command_refs.reference(SLASH, "fight") == "/duel fight"
    # autodrop n'avait que le « + » jusqu'au 28/10/2026.
    assert command_refs.reference(SLASH, "autodrop", "#salon") == "/economy autodrop #salon"
    # infinit resume était masquée du « / » (16/10) ; revenue le 28/10/2026.
    assert command_refs.reference(SLASH, "infinit resume") == "/counter resume"


def test_en_slash_une_commande_non_publiee_reste_en_plus():
    assert command_refs.reference(SLASH, "alias", "add") == "+alias add"


def test_en_prefixe_le_nom_court_et_le_prefixe_du_serveur():
    assert command_refs.reference(PREFIXE, "dailygames", nom_prefixe="jeuxjour") == "+jeuxjour"
    assert command_refs.reference(SimpleNamespace(interaction=None, clean_prefix="!"), "drop", "1000") == "!drop 1000"
