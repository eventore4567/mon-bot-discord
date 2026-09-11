"""Six portes du registre de commandes vivaient dans tools/ sans jamais
tourner en CI. Portée distincte pour chacune :

- command_integrity_v18_gate.py : boot réel (30/30 extensions), signatures,
  create/alias/permissions et cohérence slash de bout en bout.
- integrity_gate.py : cogs/integrity_hardening.py reste un durcissement (zéro
  nouvelle commande publique) et les garanties transactionnelles qu'il décrit
  existent toujours. CORRIGÉ par ce lot — voir plus bas.
- command_error_ownership_gate.py : une commande inconnue ne reçoit qu'UNE
  seule réponse SentriX (le bug historique +hyelp qui envoyait deux embeds).
- v95_slash_invites_gate.py / v97_reliability_gate.py / v98_grouped_slash_gate.py :
  trois générations successives de gates sur l'arborescence slash (inventaire
  complet, fiabilité des gaps optionnels/attachments, normalisation
  sémantique + entrypoint Railway HA) — chacune couvre des régressions
  différentes, documentées dans son propre nom (V97 "vérifie ce que V95 ne
  couvrait pas", V98 normalise ce que V95/V97 laissaient tel quel).

Bug réel trouvé et corrigé dans ce lot : integrity_gate.py cherchait encore
les trois garanties atomiques économie (dépôt/retrait, vente — "AND
cash>=?", "AND bank>=?", "AND quantity>=1") dans cogs/integrity_hardening.py,
alors que le lot Core V2 Phase 4 de cette session même les a déplacées vers
services/economy.py (comportement inchangé, voir tests/test_services_economy.py
et le commit qui a fait cette extraction) — ce gate aurait donc échoué à tort
dès ce moment-là si quiconque l'avait exécuté. Corrigé pour vérifier ces trois
marqueurs dans leur nouvel emplacement réel ; les six autres marqueurs de ce
même gate n'ont pas bougé et restent vérifiés dans cogs/integrity_hardening.py.

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
    "command_integrity_v18_gate.py",
    "integrity_gate.py",
    "command_error_ownership_gate.py",
    "v95_slash_invites_gate.py",
    "v97_reliability_gate.py",
    "v98_grouped_slash_gate.py",
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
def test_gate_passe(script):
    resultat = _run(script)
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr


def test_integrity_gate_verifie_bien_les_garanties_economie_dans_leur_nouvel_emplacement():
    """Non-régression sur le correctif lui-même : si quelqu'un retire une des
    trois garanties de services/economy.py sans y penser, ce gate doit
    recommencer à échouer plutôt que de vérifier silencieusement un fichier
    qui ne les contient plus."""
    source = (RACINE / "tools" / "integrity_gate.py").read_text(encoding="utf-8")
    assert "services" in source and "economy.py" in source
    assert "AND cash>=?" in source
    assert "AND bank>=?" in source
    assert "AND quantity>=1" in source
