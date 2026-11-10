"""10/11/2026 : un flux GitHub ne doit pas citer un fichier supprimé.

Le nettoyage des fichiers morts (PR #671 et #672) a retiré des tests que trois flux
listaient par leur nom : « sweep » et « Dashboard + product UX » échouaient avec
« file or directory not found », sans rapport avec le code modifié.
"""
from __future__ import annotations

import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
#: Flux anciens, lancés à la main ou sur des fichiers qui n'existent plus : ils citaient
#: déjà des fichiers absents avant ce garde-fou et ne tournent sur aucune PR.
FLUX_HISTORIQUES = {"log-runtime-diagnostic.yml", "one-shot-ticket-dashboard-upgrade.yml"}
CHEMIN = re.compile(r"(?:tests|tools|web|cogs|utils|database)/[A-Za-z0-9_./-]+\.py")


def test_les_flux_ne_citent_que_des_fichiers_presents():
    manquants = []
    for flux in sorted((RACINE / ".github" / "workflows").glob("*.yml")):
        if flux.name in FLUX_HISTORIQUES:
            continue
        for chemin in sorted(set(CHEMIN.findall(flux.read_text(encoding="utf-8")))):
            if not (RACINE / chemin).exists():
                manquants.append(f"{flux.name} : {chemin}")
    assert not manquants, "Fichiers cités par un flux GitHub mais absents du dépôt :\n" + "\n".join(manquants)
