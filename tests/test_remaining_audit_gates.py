"""Dernier lot de l'audit de dette technique : les 19 scripts tools/*_gate.py
et tools/*_audit.py restants, jamais exécutés en CI jusqu'ici.

Bugs réels trouvés et corrigés — même classe que les lots précédents (Core V2
Phase 4 a déplacé des garanties économie de cogs/ vers services/economy.py,
cassant des vérifications textuelles jamais réexécutées depuis) :
- v22_quality_gate.py : cherchait "last_rob"/"_economy_lock"/"cash>=?" dans
  cogs/sentrix_v22.py — déplacés vers services/economy.py::atomic_rob().
- v25_quality_gate.py : cherchait "_economy_lock"/"AND quantity>=1"/
  "AND cash>=?"/"AND bank>=?" dans cogs/integrity_hardening.py — déplacés
  vers services/economy.py (même correctif déjà appliqué à
  tools/integrity_gate.py, voir commit 90a06a0).
Les deux corrigés pour vérifier ces marqueurs dans services/economy.py ; les
autres marqueurs de chaque gate (non déplacés) restent vérifiés à leur
emplacement d'origine.

Trouvé mais PAS corrigé ici — nécessite sa propre investigation dédiée,
hors périmètre d'un audit de scripts orphelins :
language_runtime_audit.py échoue sur "la commande +setup n'est pas rattachée
au Cog Configuration testé". Investigation (voir tâche de suivi créée) :
- cogs/setup_control_center.py::install() fait bot.remove_command("setup")
  puis bot.add_cog(OfficialSetup(bot)) — remplacement délibéré et marqué
  (bot._sentrix_setup_owner = "cogs.setup_control_center"), confirmé par un
  probe direct : bot.get_command("setup").cog est bien OfficialSetup, jamais
  Configuration.
- OfficialSetup.send_setup() construit SetupView depuis
  cogs/setup_control_center.py (classe locale, ligne 515) — PAS
  cogs.configuration.SetupView, une classe différente et sans rapport.
- cogs/language_runtime.py:848 patche `configuration.SetupView` spécifiquement
  (`getattr(configuration, "SetupView", None)`) pour y ajouter le sélecteur de
  langue — donc potentiellement sur la MAUVAISE classe, celle que /setup
  n'utilise plus.
- Signal contradictoire trouvé dans le même boot : cogs/control_center_v3_language.py
  logue "FR/EN rebranché sur Control Center V4" — peut-être une couche plus
  récente qui recâble correctement la langue sur l'architecture actuelle,
  rendant le patch de language_runtime.py obsolète mais inoffensif plutôt que
  cassé. PAS confirmé dans cette session — nécessite de tracer si le panneau
  /setup réellement rendu aujourd'hui affiche encore les boutons FR/EN.
Marqué xfail strict plutôt que corrigé à l'aveugle : c'est potentiellement un
vrai defect en production sur une commande centrale (/setup), pas une simple
divergence de chemin de fichier — une correction hâtive pourrait casser
/setup pour tout le monde. Décision et investigation pour Jayden.

production_phase_audit.py échoue de façon reproductible (7 échecs sur 8
exécutions isolées) sur l'assertion `calls==3 and errors==1` après avoir posé
`_command_buffer["ping"] = [3.0, 1.0, 90.0, 50.0]` et appelé
`_flush_command_metrics()` une seule fois. Débogage fait dans cette session :
la ligne réellement écrite en base contient `calls=33, errors=11,
total_ms=990.0` — EXACTEMENT 11× les valeurs attendues (max_ms reste 50.0,
cohérent puisque MAX ne s'accumule pas). Donc le flush s'additionne 11 fois
sur le même hour_bucket avant que le test ne lise la ligne. cogs/
bot_v15_runtime.py::_install_batched_production_metrics() remplace
`ProductionPhaseRuntime._flush_command_metrics` au niveau instance
(`flush_metrics_v15`) par un UPSERT additif identique
(`calls=calls+excluded.calls`) à l'original — donc pas un simple problème de
mauvais chemin de fichier comme integrity_gate.py/v22/v25, mais une
répétition du flush lui-même (peut-être `self.monitor`, la boucle de fond de
ProductionPhaseRuntime, qui tourne pendant la fenêtre du test) — cause exacte
non confirmée dans cette session. Marqué xfail non strict (pas de garantie
que le nombre de répétitions reste stable) plutôt que corrigé à l'aveugle :
une vraie boucle de fond qui flush trop souvent pourrait aussi fausser les
métriques réelles en production, pas seulement ce test — mérite sa propre
investigation, pas un correctif de gate.

Les 15 autres scripts passent déjà tels quels, classés À CONSERVER : portée
distincte pour chacun (V2.4 UX, V2.1 intégration/legacy, style dashboard,
Enterprise Suite, +help final/Canary, style +help, FR/EN officiel,
observabilité V2 sans fuite de données, Operations Center, phase production,
readiness, Production V9, E2E synthétique + résilience PostgreSQL/Redis/
OpenAI, audit statique repo, usabilité quotidienne, acceptation utilisateur).

Même patron que tous les lots précédents : sous-processus vers le vrai
script."""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
RACINE = pathlib.Path(__file__).resolve().parent.parent

SCRIPTS_OK = [
    "intelligent_ux_v24_gate.py",
    "v21_quality_gate.py",
    "v22_quality_gate.py",
    "v25_quality_gate.py",
    "command_style_dashboard_tools_audit.py",
    "enterprise_suite_audit.py",
    "final_runtime_polish_audit.py",
    "help_clean_style_audit.py",
    "language_official_audit.py",
    "observability_v2_audit.py",
    "operations_center_audit.py",
    "production_readiness_audit.py",
    "production_v9_audit.py",
    "real_e2e_resilience_audit.py",
    "repo_audit.py",
    "usability_runtime_audit.py",
    "user_acceptance_audit.py",
]


def _run(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RACINE / "tools" / script)],
        capture_output=True,
        text=True,
        cwd=str(RACINE),
        env={**os.environ, "DISCORD_TOKEN": "ci.fake.token"},
        timeout=90,
    )


@pytest.mark.parametrize("script", SCRIPTS_OK)
def test_gate_final_lot_passe(script):
    resultat = _run(script)
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr


def test_v22_et_v25_verifient_bien_les_garanties_economie_dans_leur_nouvel_emplacement():
    """Non-régression sur les deux correctifs eux-mêmes."""
    for script in ("v22_quality_gate.py", "v25_quality_gate.py"):
        source = (RACINE / "tools" / script).read_text(encoding="utf-8")
        assert "services" in source and "economy.py" in source
        assert "_economy_lock" in source


@pytest.mark.xfail(
    strict=True,
    reason=(
        "/setup n'est plus rattaché au Cog Configuration que ce gate teste — "
        "cogs/setup_control_center.py::install() a délibérément remplacé la "
        "commande (bot._sentrix_setup_owner marqué), mais utilise sa PROPRE "
        "classe SetupView (ligne 515), différente de cogs.configuration."
        "SetupView. cogs/language_runtime.py patche spécifiquement cette "
        "dernière pour le sélecteur FR/EN — potentiellement la mauvaise "
        "classe. Signal contradictoire : cogs/control_center_v3_language.py "
        "logue un re-câblage FR/EN sur 'Control Center V4', peut-être déjà "
        "correct sur la bonne classe — non confirmé. Possible defect "
        "production sur une commande centrale ; nécessite investigation "
        "dédiée (le panneau /setup réellement rendu affiche-t-il encore FR/EN "
        "?) avant toute correction, pas une simple mise à jour de chemin. "
        "Décision et investigation pour Jayden — voir tâche de suivi créée."
    ),
)
def test_language_runtime_audit_setup_correctement_rattache():
    resultat = _run("language_runtime_audit.py")
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr


@pytest.mark.xfail(
    strict=False,
    reason=(
        "Reproductible (7/8 exécutions isolées) : après avoir posé "
        "_command_buffer['ping'] = [3.0, 1.0, 90.0, 50.0] et appelé "
        "_flush_command_metrics() UNE fois, la ligne écrite en base contient "
        "calls=33, errors=11, total_ms=990.0 — exactement 11x les valeurs "
        "attendues (max_ms reste 50.0, cohérent). Le flush s'additionne "
        "plusieurs fois sur le même hour_bucket avant la lecture du test. "
        "cogs/bot_v15_runtime.py::_install_batched_production_metrics() "
        "remplace _flush_command_metrics au niveau instance par un UPSERT "
        "additif identique à l'original (pas un problème de mauvais fichier "
        "comme integrity_gate.py/v22/v25) — cause exacte des répétitions "
        "(boucle self.monitor ? appel concurrent ?) non confirmée dans cette "
        "session. Non strict : le nombre de répétitions n'est pas garanti "
        "stable. Pourrait aussi fausser des métriques réelles en production, "
        "pas seulement ce test — investigation dédiée pour Jayden, voir "
        "tâche de suivi créée."
    ),
)
def test_production_phase_audit_metriques_commandes_non_dupliquees():
    resultat = _run("production_phase_audit.py")
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr
