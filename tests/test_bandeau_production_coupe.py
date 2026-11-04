"""03/11/2026 : en production, aucune bande en tête des cartes de commandes."""
from pathlib import Path


def test_bande_coupee_par_defaut_en_production():
    source = (Path(__file__).resolve().parents[1] / "utils" / "sentrix_panels.py").read_text(encoding="utf-8")
    assert 'environ.get("SENTRIX_BANDEAUX", "0") == "1"' in source
