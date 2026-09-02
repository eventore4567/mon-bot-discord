"""Le registre reel des commandes, verifie dans un processus a part.

Le demarrage complet du bot patche des objets globaux de discord.py
(Messageable.send, Context.send, la pile de style). Le faire au milieu de la
suite cassait cinq tests de rendu qui s'executaient ensuite. La verification
tourne donc dans son propre processus.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

RACINE = pathlib.Path(__file__).resolve().parent.parent


def test_le_registre_des_commandes_est_coherent():
    """Aucun doublon, aucun alias orphelin, une politique d'acces par commande,
    et les deux gardes de permissions effectivement installees."""
    resultat = subprocess.run(
        [sys.executable, str(RACINE / "tools" / "audit_registre.py")],
        capture_output=True,
        text=True,
        cwd=str(RACINE),
        env={**os.environ, "DISCORD_TOKEN": "x"},
        timeout=600,
    )
    assert resultat.returncode == 0, resultat.stdout[-4000:] + resultat.stderr[-2000:]
