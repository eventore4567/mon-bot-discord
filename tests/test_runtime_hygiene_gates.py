"""Portes « runtime réel / extensions » qui vivaient dans tools/ sans jamais
tourner en CI. Les deux premières (dead_module_gate.py, listener_budget_gate.py)
font un boot réel des 51 extensions.

dead_module_gate.py : signale les fichiers cogs/*.py qu'aucun texte vivant
ne nomme. Deux bugs réels trouvés et corrigés dans ce lot :
1. Comme permission_coverage_gate.py : le process ne se terminait jamais
   après avoir imprimé son verdict (aucun bot.db.close() ni annulation des
   tâches de fond).
2. Faux positifs en cascade : un module retenu via l'allowlist RETENUS
   (vivant confirmé manuellement malgré l'absence dans sys.modules, ex.
   final_runtime_polish) était néanmoins EXCLU du balayage textuel de
   "code vivant" pour ses propres imports différés — sentrix_v2, sentrix_v21,
   sentrix_v22 et sentrix_intelligent_ux (tous importés à l'intérieur de
   final_runtime_polish.py, jamais au niveau module) ressortaient donc comme
   orphelins alors qu'ils sont bel et bien atteints en production via lui.
   Confirmé par lecture directe : cogs/final_runtime_polish.py fait bien
   `from .sentrix_v22 import SentriXV22` (et les trois autres) à la ligne 125-127
   et 317. Corrigé en incluant aussi les fichiers de RETENUS dans le balayage.

   Après ces deux correctifs, 3 modules restent authentiquement orphelins :
   log_rectangle_v25, premium_logs, premium_logs_v2. Preuve indépendante de
   leur mort réelle (pas seulement l'absence de référence) :
   tests/test_discord_ui_contract.py::test_runtime_no_longer_installs_competing_log_help_layers
   vérifie déjà explicitement que cogs/__init__.py ne les installe plus — un
   retrait délibéré déjà documenté et testé ailleurs, pas une découverte.
   Non supprimés ici (aucun script n'est supprimé uniquement parce qu'il
   n'est pas appelé) — à la discrétion de Jayden.

listener_budget_gate.py : même bug de blocage, corrigé pareil. Constat
actuellement réel et non résolu (pas une régression de ce lot — les budgets
datent du 2026-09-01, la dérive est antérieure à cet audit) : 5 événements
dépassent leur budget enregistré (on_command_completion 14/13, on_member_join
17/16, on_member_remove 8/7, on_message 21/20, on_ready 32/28). Marqué xfail
strict plutôt que silencieusement relevé : la philosophie même de cette porte
est qu'une hausse doit être un CHOIX conscient (relever BUDGETS dans le
script), jamais une dérive qu'on maquille. Décision produit qui revient à
Jayden, pas à corriger ici sans preuve de bug.

Les huit scripts suivants sont de l'analyse statique pure (rapide, pas de
boot) sur le Bot V10/V11/V13/Excellence/Mastery : bot_v11_custom_command_gate.py,
bot_v11_resilience_gate.py, bot_v13_gate.py, v10_compile_gate.py,
bot_excellence_audit.py, bot_mastery_audit.py, runtime_debt_gate.py passent
tous déjà tels quels (à conserver, aucune régression). bot_mastery_audit.py a
révélé en passant que cogs/ai_api_hotfix.py s'exécute bien au boot (log
"OPENAI_API_KEY is missing" émis par son propre logger) — contredit la
conclusion précédente de docs/core-v2-audit-ai-patch-stack.md qui le
qualifiait de code mort ; à corriger dans ce document séparément, hors
périmètre de ce lot.

bot_v10_audit.py : bug réel trouvé, partiellement corrigé.
1. CORRIGÉ : l'assertion `'"cogs.bot_v10"' in boot` supposait que bot_v10
   était déclaré directement dans railway_boot.py. Il ne l'est plus — il est
   chargé indirectement par cogs/slash_reliability_v7.py::_install_bot_v10()
   (confirmé par lecture : `from . import bot_v10` puis
   `await bot_v10.setup(bot)`), et c'est slash_reliability_v7 qui est
   l'extension réellement déclarée. Assertion mise à jour pour vérifier ce
   chemin réel plutôt que l'ancien.
2. NON CORRIGÉ, marqué xfail : web/platform_v10.py (le tableau de bord V10)
   n'est plus référencé nulle part dans le code vivant (aucun `import
   platform_v10` en dehors de tools/) — confirmé indépendamment par
   runtime_reachability_audit.py, qui le liste aussi comme ORPHAN_CANDIDATE.
   cogs/bot_v10.py (le côté Discord) reste bien vivant ; seul son tableau de
   bord semble avoir été débranché. Décision produit pour Jayden : restaurer
   le branchement, supprimer web/platform_v10.py explicitement, ou modifier
   ce gate pour ne plus l'exiger — pas une suppression silencieuse ici.

runtime_reachability_audit.py : toujours purement informatif (n'échoue
jamais, "aucune suppression automatique" dans son propre message). Recoupe
5 des 7 candidats de dead_module_gate.py (log_rectangle_v25, premium_logs,
premium_logs_v2, stale_discord_app_detector, command_error_probe) mais couvre
un périmètre bien plus large (tout le dépôt : scripts racine, web/, HA) — pas
redondant, complémentaire. À conserver."""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
RACINE = pathlib.Path(__file__).resolve().parent.parent


def _run(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RACINE / "tools" / script)],
        capture_output=True,
        text=True,
        cwd=str(RACINE),
        env={**os.environ, "DISCORD_TOKEN": "ci.fake.token"},
        timeout=60,
    )


def test_dead_module_gate_ne_signale_aucun_faux_positif_connu():
    resultat = _run("dead_module_gate.py")
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr
    for module in ("sentrix_v2", "sentrix_v21", "sentrix_v22", "sentrix_intelligent_ux"):
        assert module not in resultat.stdout.split("Modules que plus rien n'atteint :")[-1], (
            f"{module} ne doit plus ressortir comme orphelin (atteint via final_runtime_polish.py)"
        )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "5 événements dépassent leur budget enregistré le 2026-09-01 "
        "(on_command_completion, on_member_join, on_member_remove, on_message, "
        "on_ready) — dérive antérieure à cet audit, pas une régression de ce "
        "lot. Décision produit pour Jayden : relever consciemment les budgets "
        "dans tools/listener_budget_gate.py, ou investiguer/retirer les "
        "handlers en trop. Ce test doit repasser XPASS (et perdre son xfail) "
        "une fois la décision prise."
    ),
)
def test_listener_budget_gate_dans_les_limites():
    resultat = _run("listener_budget_gate.py")
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr


STATIC_SCRIPTS_OK = [
    "runtime_debt_gate.py",
    "bot_v11_custom_command_gate.py",
    "bot_v11_resilience_gate.py",
    "bot_v13_gate.py",
    "v10_compile_gate.py",
    "bot_excellence_audit.py",
    "bot_mastery_audit.py",
]


@pytest.mark.parametrize("script", STATIC_SCRIPTS_OK)
def test_gate_runtime_passe(script):
    resultat = _run(script)
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr


def test_runtime_reachability_audit_sexecute_et_ne_bloque_jamais():
    """Purement informatif par conception (voir son propre message "aucune
    suppression automatique") — ce test confirme juste qu'il tourne toujours
    sans lever, pour garder son rapport visible dans la sortie CI."""
    resultat = _run("runtime_reachability_audit.py")
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr
    assert "ORPHAN_CANDIDATE" in resultat.stdout


def test_bot_v10_audit_verifie_le_chemin_de_chargement_reel():
    """L'assertion corrigée (bot_v10 chargé via slash_reliability_v7, pas
    déclaré directement) doit rester vraie."""
    source = (RACINE / "tools" / "bot_v10_audit.py").read_text(encoding="utf-8")
    assert '"cogs.slash_reliability_v7"' in source
    assert "await bot_v10.setup(bot)" in source


@pytest.mark.xfail(
    strict=True,
    reason=(
        "web/platform_v10.py (tableau de bord V10) n'est plus importé nulle "
        "part dans le code vivant — confirmé indépendamment par "
        "runtime_reachability_audit.py (ORPHAN_CANDIDATE web/platform_v10.py). "
        "cogs/bot_v10.py (le côté Discord) reste vivant, seul le tableau de "
        "bord semble débranché. Décision produit pour Jayden : restaurer le "
        "branchement, supprimer le fichier explicitement, ou alléger ce gate — "
        "pas une suppression silencieuse ici. Ce test doit repasser XPASS "
        "(et perdre son xfail) une fois la décision prise."
    ),
)
def test_bot_v10_audit_complet():
    resultat = _run("bot_v10_audit.py")
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr
