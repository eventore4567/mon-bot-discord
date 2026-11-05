"""Bande fine en tête des cartes de commandes.

03/11/2026 : retirée en production (« c'est moche »).
05/11/2026 : rétablie à la demande (« bannière ultra fine dans setup comme les
autres », « pas de bannière sur les commandes »). Toujours désactivable avec
SENTRIX_BANDEAUX=0.
"""
from pathlib import Path


def test_bande_fine_active_par_defaut_en_production():
    source = (Path(__file__).resolve().parents[1] / "utils" / "sentrix_panels.py").read_text(encoding="utf-8")
    assert 'environ.get("SENTRIX_BANDEAUX", "1") == "1"' in source
