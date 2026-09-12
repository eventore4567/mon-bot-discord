"""Trois portes de permissions vivaient dans tools/ sans jamais tourner en CI
(aucun test ne les invoquait — seulement des lancements manuels documentés
dans des messages de commit). Chacune charge réellement les 51 extensions de
production et vérifierait un bug de classe différente si l'une régressait :

- permission_coverage_gate.py : une racine de commande absente de
  utils/access_matrix.py (exactement le bug historique sur "gameseason").
- command_permission_group_consistency_audit.py : une sous-commande dangereuse
  héritant silencieusement du niveau public de son groupe (le bug historique
  sur +giveaway/+giveaway list), ou toute commande fail-closed non classée.
- permission_guard_audit.py : les frontières de sécurité invariantes (aide
  publique, commandes membres publiques, administration protégée, blacklist
  owner-only, fail-closed par défaut) sur les deux chemins préfixe et slash.

Suit exactement le patron déjà établi par tests/test_coherence_components_v2.py
pour ce type d'audit "boot réel puis vérifie" : un sous-processus, pas une
réimplémentation — la moindre divergence entre le test et le vrai outil
recréerait le problème que ce lot corrige (un audit qui existe mais qu'on
ne fait jamais tourner)."""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
RACINE = pathlib.Path(__file__).resolve().parent.parent


def _run(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RACINE / "tools" / script)],
        capture_output=True,
        text=True,
        cwd=str(RACINE),
        env={**os.environ, "DISCORD_TOKEN": "ci.fake.token"},
        timeout=120,
    )


def test_permission_coverage_gate_toutes_les_racines_sont_classees():
    resultat = _run("permission_coverage_gate.py")
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr


def test_command_permission_group_consistency_aucune_commande_fail_closed():
    resultat = _run("command_permission_group_consistency_audit.py")
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr


def test_permission_guard_audit_frontieres_de_securite_invariantes():
    resultat = _run("permission_guard_audit.py")
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr
