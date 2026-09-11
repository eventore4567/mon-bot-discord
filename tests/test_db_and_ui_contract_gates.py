"""Six portes « base de données » et « Components V2 / Discord UI » vivaient
dans tools/ sans jamais tourner en CI. Toutes passent déjà telles quelles —
aucun bug de gate trouvé — sauf une correction de documentation découverte en
passant (voir plus bas) :

- load_stress_audit.py : 1000 écritures + 200 lectures concurrentes contre la
  vraie base, snapshot cohérent — détecterait une régression de verrouillage
  transactionnel (la même classe de bug que services/economy.py corrige,
  voir tests/test_services_economy.py) avant qu'elle n'atteigne la production.
- refonte_gate.py : suivi de progression de la recomposition Components V2
  (bannière + sections vs embed classique) — purement informatif par
  conception (aucune condition d'échec dans le script), toujours à conserver
  pour la visibilité qu'il donne sur l'avancement réel.
- no_emoji_commands_audit.py : le thème visuel canonique (titres sobres, pas
  d'emoji décoratif) reste cohérent dans le renderer central.
- ux_quality_audit.py : aide officielle, syntaxes lisibles, centre +setup
  canonique — boot réel, 301 commandes vérifiées.
- web_interaction_audit.py : API de recours publique non interceptée par le
  verrou Administrateur, scripts dashboard syntaxiquement valides, boutons
  statiques réellement référencés par leur JavaScript.
- ai_api_hotfix_gate.py : confirme que cogs/ai_api_hotfix.py::setup() est
  bien appelé au boot — a permis de CORRIGER une erreur dans
  docs/core-v2-audit-ai-patch-stack.md (Phase 4, cette même session), qui
  affirmait ce module mort faute d'avoir trouvé son appelant réel
  (cogs/remove_code_command/__init__.py — le PAQUET vivant qui masque le
  fichier plat mort du même nom, voir docs/core-v2-audit-technical-debt.md
  #11 — importe et installe ai_api_hotfix, un nom de module sans aucun
  rapport avec ce qu'il fait). Preuve indépendante déjà observée dans le lot
  précédent : bot_mastery_audit.py affiche le log
  "[ERROR] bot.ai-api-hotfix: SentriX AI: OPENAI_API_KEY is missing" à
  chaque boot réel.

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
    "load_stress_audit.py",
    "refonte_gate.py",
    "no_emoji_commands_audit.py",
    "ux_quality_audit.py",
    "web_interaction_audit.py",
    "ai_api_hotfix_gate.py",
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
def test_gate_db_ou_ui_passe(script):
    resultat = _run(script)
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr


def test_ai_api_hotfix_est_bien_installe_via_remove_code_command():
    """Verrouille la chaîne d'installation réelle découverte par ce lot, pour
    que la documentation corrigée ne redevienne pas fausse en silence."""
    loader = (RACINE / "cogs" / "remove_code_command" / "__init__.py").read_text(encoding="utf-8")
    assert "from ..ai_api_hotfix import setup as install_ai_api_hotfix" in loader
    assert "await install_ai_api_hotfix(bot)" in loader
    init_text = (RACINE / "cogs" / "__init__.py").read_text(encoding="utf-8")
    assert "from .remove_code_command import install as install_remove_code_command" in init_text
