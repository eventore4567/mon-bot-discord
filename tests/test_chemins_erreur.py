"""Les onze chemins d'erreur restent des interfaces a part entiere.

Une erreur est ce que l'utilisateur voit le plus souvent et ce qui est le moins
teste, parce qu'il faut provoquer la panne pour la voir. Ce test construit
chaque erreur et verifie le panneau que le module canonique rendrait :
banniere, titre, sections reelles, pied d'identite.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

RACINE = pathlib.Path(__file__).resolve().parent.parent


def test_les_onze_chemins_d_erreur_sont_conformes():
    resultat = subprocess.run(
        [sys.executable, str(RACINE / "tools" / "valid_erreurs.py")],
        capture_output=True,
        text=True,
        cwd=str(RACINE),
        env={**os.environ, "DISCORD_TOKEN": "x"},
        timeout=300,
    )
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr
    assert "11/11 chemins d'erreur conformes" in resultat.stdout
