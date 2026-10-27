"""utils/audit_entries : une entrée d'audit SANS cible ne fait plus planter les écouteurs."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import audit_entries  # noqa: E402


class _EntreeSansCible:
    _target_id = None

    @property
    def target(self):  # comme discord.py : int(None) dans Object
        raise TypeError("int() argument must be a string, a bytes-like object or a real number, not 'NoneType'")


def test_entree_sans_cible():
    assert audit_entries.cible(_EntreeSansCible()) is None
    assert audit_entries.cible_id(_EntreeSansCible()) is None


def test_entree_avec_cible():
    entree = SimpleNamespace(_target_id="123", target=SimpleNamespace(id=123))
    assert audit_entries.cible_id(entree) == 123
    assert audit_entries.cible(entree).id == 123
