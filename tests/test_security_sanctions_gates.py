"""Cinq portes « sécurité / sanctions » vivaient dans tools/ sans jamais
tourner en CI. Portée distincte pour chacune, aucun bug trouvé (les 5
passent déjà tels quels) :

- security_runtime_audit.py : anti-nuke persistant, verrous critiques,
  PANIC et l'arborescence complète +security V3 (sanctions liées à la
  sécurité serveur).
- security_v2_audit.py : compteur anti-nuke, rollback de rôles, incidents,
  sauvegardes automatiques, règles propriétaire et branchement dashboard —
  la génération précédente de la même famille, portée différente (les
  branchements plutôt que l'arborescence de commandes).
- instance_isolation_audit.py : identités séparées entre bots (SentriX vs
  Bot'Odboug), espaces de noms Redis/PostgreSQL et snapshots isolés —
  empêche qu'un bug de configuration mélange les données de deux bots.
- accessibility_v23_gate.py : accessibilité V2.3, zéro nouvelle commande
  (une régression ici ajouterait silencieusement une commande publique).
- ai_intent_fuzz_gate.py : une phrase de discussion normale ne doit jamais
  déclencher une action sensible (sanction/paiement/vol) via le routeur
  d'intentions naturelles ; à l'inverse, une formulation d'action explicite
  doit continuer à produire un plan — directement lié aux sanctions, car
  c'est ce qui empêche +ai de bannir quelqu'un sur un simple "ban-le" dit en
  passant dans une conversation.

Même patron que les lots précédents : sous-processus vers le vrai script."""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
RACINE = pathlib.Path(__file__).resolve().parent.parent

SCRIPTS = [
    "security_runtime_audit.py",
    "security_v2_audit.py",
    "instance_isolation_audit.py",
    "accessibility_v23_gate.py",
    "ai_intent_fuzz_gate.py",
]


def _run(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RACINE / "tools" / script)],
        capture_output=True,
        text=True,
        cwd=str(RACINE),
        env={**os.environ, "DISCORD_TOKEN": "ci.fake.token"},
        timeout=60,
    )


@pytest.mark.parametrize("script", SCRIPTS)
def test_gate_securite_passe(script):
    resultat = _run(script)
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr
