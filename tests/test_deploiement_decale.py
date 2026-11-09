"""09/11/2026 : le secours se redéploie APRÈS le primaire validé (branche standby-stable),
pour que SentriX ne s'arrête jamais en entier pendant un déploiement."""
from pathlib import Path

import yaml

FLUX = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "railway-ha-staggered-deploy.yml"


def test_le_deploiement_decale_suit_la_branche_de_production():
    flux = yaml.safe_load(FLUX.read_text(encoding="utf-8"))
    declencheurs = flux.get("on") or flux.get(True)
    assert "dashboard-refonte-2026-09" in declencheurs["push"]["branches"]
    tache = flux["jobs"]["sync-standby-after-primary"]
    assert "refs/heads/dashboard-refonte-2026-09" in tache["if"]
    texte = FLUX.read_text(encoding="utf-8")
    assert "heads/standby-stable" in texte and "selfless-tenderness - mon-bot-discord" in texte
