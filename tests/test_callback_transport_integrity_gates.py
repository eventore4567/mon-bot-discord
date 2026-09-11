"""Sept portes d'intégrité (transport d'interaction, cycle de vie des erreurs
slash, nettoyage du "thinking", garde defer/send) vivaient dans tools/ sans
jamais tourner en CI — seulement des lancements manuels. Chacune fait de
l'analyse statique AST pure (aucun boot du bot, rapide) sur UN fichier de
garde précis, vérifiant qu'il conserve la forme exacte dont dépend son
câblage sur railway_boot.py. Portée distincte pour chacune, aucune
redondance :

- interaction_transport_gate.py : cogs/interaction_transport_guard.py reste
  câblé sur le Gateway (pas un ancien endpoint HTTP périmé).
- command_error_probe_gate.py / stale_discord_app_gate.py : les deux cogs
  associés restent des outils de diagnostic MANUELS, jamais chargés en
  production — vérifié en lisant railway_boot.py, pas juste supposé.
- slash_error_lifecycle_gate.py : le defer est bien refermé sur succès ET sur
  erreur, la collision de schéma legacy reste mise en quarantaine.
- slash_thinking_gate.py : le relais inter-instance reste public, sans
  toucher aux permissions, avec un cycle de vie de defer observable.
- defer_send_audit.py / deferred_context_guard_gate.py : le résolveur global
  defer/send (cogs/deferred_context_response_guard.py) garde la forme exacte
  qui rend inutile tout ancien motif ctx.defer()+ctx.send() par commande, et
  charge bien AVANT la garde d'erreur finale sur railway_boot.py.

Aucune n'a trouvé de régression lors de cet audit (toutes les assertions
portent sur du code encore présent et inchangé) — seulement jamais exécutées
en continu jusqu'à ce lot. Même patron que tests/test_coherence_components_v2.py
et tests/test_permission_audit_gates.py : sous-processus vers le vrai script,
pas de réimplémentation."""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
RACINE = pathlib.Path(__file__).resolve().parent.parent

SCRIPTS = [
    "interaction_transport_gate.py",
    "command_error_probe_gate.py",
    "slash_error_lifecycle_gate.py",
    "slash_thinking_gate.py",
    "stale_discord_app_gate.py",
    "defer_send_audit.py",
    "deferred_context_guard_gate.py",
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
def test_gate_ast_passe(script):
    resultat = _run(script)
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr
