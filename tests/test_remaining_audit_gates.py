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

Investigation dédiée terminée (session suivante) — RÉSOLU, corrigé, xfail levé :
language_runtime_audit.py testait la mauvaise classe. Preuve obtenue par un
probe de boot réel (instanciation directe de la vraie SetupView utilisée par
+setup, appel de .render()/.composer(), inspection de .children et du payload
Discord sérialisé) :
- cogs/setup_control_center.py::install() fait bot.remove_command("setup")
  puis bot.add_cog(OfficialSetup(bot)) — remplacement délibéré et marqué
  (bot._sentrix_setup_owner = "cogs.setup_control_center"). Confirmé :
  bot.get_command("setup").cog est bien OfficialSetup, jamais Configuration.
- OfficialSetup.send_setup() construit SetupView depuis
  cogs/setup_control_center.py (classe locale, ligne 515) — PAS
  cogs.configuration.SetupView (V6), une classe différente, jamais rendue en
  production bien que toujours chargée.
- cogs/control_center_v3_language.py rebranche le sélecteur FR/EN
  (OfficialLanguageSelect, custom_id="sentrix:setup:official:language") sur
  cogs.setup_control_center.SetupView — la vraie classe — pas sur
  cogs.configuration.SetupView. Le patch de cogs/language_runtime.py:848 sur
  cette dernière est confirmé vestigial mais inoffensif : il cible une classe
  qui n'est plus jamais instanciée par +setup.
- Le probe confirme le sélecteur present à la fois sur l'instance rendue
  (.children après .render()) ET dans le payload Discord final sérialisé
  (.composer() puis .to_components(), recherche récursive car
  setup_control_center.SetupView imbrique tout dans UN Container Components V2
  — contrairement à l'ancienne classe à plat que le gate testait avant).
language_runtime_audit.py a été réécrit pour construire et vérifier la VRAIE
classe active (cogs.setup_control_center.SetupView) au lieu de
cogs.configuration.SetupView (V6, jamais rendue) : ownership +setup via
bot._sentrix_setup_owner et le type du Cog réel, marqueurs de classe
(_sentrix_control_center_v3_language, _sentrix_language_payload_guard),
présence du sélecteur sur la page d'accueil réellement rendue, absence hors
accueil, et présence dans le payload Components V2 final envoyé à Discord.
+setup n'a jamais été cassé en production — seul le gate testait la mauvaise
classe.

Investigation dédiée terminée (session suivante) — RÉSOLU, corrigé, xfail levé :
production_phase_audit.py échouait de façon reproductible (7 échecs sur 8
exécutions isolées) sur l'assertion `calls==3 and errors==1` après avoir posé
`_command_buffer["ping"] = [3.0, 1.0, 90.0, 50.0]` et appelé
`_flush_command_metrics()` une seule fois. Le suspect initial (`self.monitor`,
la boucle de fond de ProductionPhaseRuntime, qui pourrait flusher plusieurs
fois pendant la fenêtre du test) est écarté par une instrumentation directe :
`_session_started(bot)` renvoie False dans ce harnais (le bot ne se connecte
jamais réellement à Discord), donc `self.monitor.start()` ne tourne jamais, et
`_flush_command_metrics`/`flush_metrics_v15` n'est appelé qu'UNE seule fois
par exécution — confirmé sur 15 exécutions consécutives, y compris les
échecs. La cause réelle est une fuite d'isolation de base de données, pas une
répétition du flush : `runtime_audit()` fait
`os.environ["DATABASE_PATH"] = path` PUIS `import main`, mais `config` est
déjà importé transitivement plus haut dans ce même fichier (`from cogs import
production_phase_runtime as phase` → `cogs/production_phase_runtime.py` →
`from utils import embeds` → `import config`), donc `config.DATABASE_PATH =
os.getenv("DATABASE_PATH", "database/bot.db")` s'est déjà figé sur la valeur
par défaut avant que la variable d'environnement ne soit positionnée.
`main.BotAllInOne()` relit cette constante déjà figée et se connecte à la
VRAIE base locale (`database/bot.db`) au lieu du dossier temporaire — chaque
exécution du script ajoute donc +3/+1/+90 au même hour_bucket via l'UPSERT
additif (parfaitement correct et voulu pour de vraies métriques de
production), sur une ligne qui s'accumule d'une exécution à l'autre au lieu
de repartir de zéro. Le nombre de répétitions observé (11×) n'était qu'un
instantané de cette accumulation au moment du test — d'où le xfail non
strict, la valeur exacte n'ayant jamais été stable. Prouvé en lisant
directement `database/bot.db` pendant l'investigation : la ligne
`hour_bucket`/`ping` y grossissait à chaque exécution du script, avant
correctif. Corrigé en forçant `main.config.DATABASE_PATH = path` juste après
`import main` dans `runtime_audit()` — ni `cogs/production_phase_runtime.py`
ni `cogs/bot_v15_runtime.py` (la sémantique additive de l'UPSERT y est
correcte et volontaire) n'ont été touchés ; seul le harnais d'isolation de cet
audit l'était. Vérifié sur 20 exécutions consécutives, 20/20 succès, et
`database/bot.db` n'est plus écrit par ce script.

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


def test_language_runtime_audit_setup_correctement_rattache():
    resultat = _run("language_runtime_audit.py")
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr


def test_production_phase_audit_metriques_commandes_non_dupliquees():
    resultat = _run("production_phase_audit.py")
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr
