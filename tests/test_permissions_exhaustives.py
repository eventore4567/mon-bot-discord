"""Les six profils, face aux 536 commandes reelles.

Les tests de la matrice verifient des commandes CHOISIES. Celui-ci part de
l'inverse : il charge le bot complet et demande a la matrice ce qu'elle repond
a chaque profil, pour chaque commande. Une commande oubliee dans la matrice, ou
un administrateur qui atteindrait une commande reservee au proprietaire, se
voit alors immediatement.

Il verifie aussi la question qui compte vraiment : une regle de Setup
peut-elle ouvrir une commande reservee ? Si oui, un administrateur hostile
contourne toute la hierarchie en trois clics.

Comme le demarrage complet patche des objets globaux de discord.py, il tourne
dans son propre processus.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import tempfile

RACINE = pathlib.Path(__file__).resolve().parent.parent


def test_aucune_permission_incoherente_sur_les_commandes_reelles():
    # L'environnement doit être fixé avant le spawn (sitecustomize est précoce).
    with tempfile.TemporaryDirectory(prefix="sentrix-exhaustive-permissions-") as temporary_dir:
        resultat = subprocess.run(
            [sys.executable, str(RACINE / "tools" / "audit_permissions.py")],
            capture_output=True,
            text=True,
            cwd=str(RACINE),
            env={**os.environ, "DISCORD_TOKEN": "x", "DATABASE_PATH": str(pathlib.Path(temporary_dir) / "bot.db")},
            timeout=900,
        )
    sortie = resultat.stdout
    assert resultat.returncode == 0, sortie[-5000:] + resultat.stderr[-2000:]
    # Garde-fou du harnais : un audit sur un registre vide passerait sans rien
    # verifier du tout.
    match = re.search(r"(?m)^commandes auditees : (\d+)\s*$", sortie)
    assert match is not None, "L'audit n'a pas imprimé son compteur de commandes"
    assert int(match.group(1)) >= 500, (
        f"Inventaire anormalement réduit : {match.group(1)} commandes (minimum 500)"
    )
    assert "aucune anomalie de permission" in sortie
    assert "aucune regle de configuration ne contourne la hierarchie" in sortie
    assert "aucune commande slash non publique visible de tous" in sortie
