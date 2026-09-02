"""Où part chaque journal, et lesquels ne doivent pas partir du tout.

Deux défauts constatés en production :

- chaque réédition d'un panneau par SentriX produisait un faux
  « Message désépinglé », parce que Discord place l'état épinglé dans TOUTE
  mise à jour de message ;
- un rôle donné à un membre partait dans les logs Rôles, où l'on cherche
  l'historique du rôle lui-même — et le noyait sous les mouvements de chaque
  membre du serveur.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "x")

import pytest  # noqa: E402

from utils.log_categories import resolve  # noqa: E402


class _Charge:
    """Un RawMessageUpdateEvent réduit à ce que le filtre lit."""

    def __init__(self, data, cache=None):
        self.data = data
        self.cached_message = cache


class _EnCache:
    def __init__(self, pinned):
        self.pinned = pinned


def _filtre():
    from cogs.create_sentrix_v3 import CreateSentriXV3

    return CreateSentriXV3._changement_d_epinglage


@pytest.mark.parametrize(
    "libelle,charge,pinned,attendu",
    [
        # Le cache tranche : on compare l'avant et l'après.
        ("cache, état inchangé", _Charge({"pinned": False}, _EnCache(False)), False, False),
        ("cache, désépinglé", _Charge({"pinned": False}, _EnCache(True)), False, True),
        ("cache, épinglé", _Charge({"pinned": True}, _EnCache(False)), True, True),
        (
            "cache, simple édition d'un message épinglé",
            _Charge({"pinned": True, "content": "x"}, _EnCache(True)),
            True,
            False,
        ),
        # Sans cache : épingler ne modifie pas le message, donc une charge qui
        # porte un contenu ou une date d'édition est une édition.
        ("réédition de panneau", _Charge({"pinned": False, "content": "x"}), False, False),
        (
            "édition horodatée",
            _Charge({"pinned": False, "edited_timestamp": "2026-01-01"}),
            False,
            False,
        ),
        ("vrai désépinglage", _Charge({"pinned": False}), False, True),
        ("vrai épinglage", _Charge({"pinned": True}), True, True),
    ],
)
def test_seul_un_vrai_changement_d_epinglage_est_journalise(
    libelle, charge, pinned, attendu
):
    assert _filtre()(charge, pinned) is attendu, libelle


@pytest.mark.parametrize("evenement", ["role_add", "role_remove", "member_roles"])
def test_un_role_donne_a_un_membre_va_dans_les_logs_membres(evenement):
    """C'est le membre qui change, pas le rôle."""
    assert resolve(evenement)[0] == "members"


@pytest.mark.parametrize("evenement", ["role_create", "role_delete", "role_update"])
def test_les_logs_roles_ne_gardent_que_le_role_lui_meme(evenement):
    """Création, suppression, permissions : là, le rôle EST le sujet."""
    assert resolve(evenement)[0] == "roles"
