"""« + » retiré (30/10/2026) : l'aide ne montre plus que les commandes « / »."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import help_complete_v79 as aide  # noqa: E402
from cogs import prefix_deprecation as avis  # noqa: E402


def test_le_prefixe_est_coupe_par_defaut(monkeypatch):
    monkeypatch.delenv("SENTRIX_PREFIXE_ACTIF", raising=False)
    assert avis.prefixe_actif() is False
    assert "ont été supprimées" in avis.texte_retire(SimpleNamespace(mention="<@1>"))


def test_l_aide_ne_montre_plus_le_plus(monkeypatch):
    monkeypatch.setenv("SENTRIX_PREFIXE_ACTIF", "0")
    entree = SimpleNamespace(slash_name="ban", prefix_command=SimpleNamespace(qualified_name="ban", aliases=[]),
                             slash_command=None, name="ban")
    monkeypatch.setattr(aide, "_short_name", lambda c: c.qualified_name)
    import utils.slash_ids as ids
    monkeypatch.setattr(ids, "mention", lambda chemin: f"/{chemin}")
    assert aide._title(entree) == "/ban"
    assert aide._prefix_usage(entree, "+") is None
