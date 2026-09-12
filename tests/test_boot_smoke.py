"""Milestone 1 (SentriX Core Reliability), priorité P0 #3 : test de smoke-boot
dédié. Charge les 51 extensions réelles (main.py + les 21 ajoutées par
railway_boot.py) dans un sous-processus jetable et échoue clairement si le bot
ne démarre pas — garantie qui n'existait auparavant qu'incidemment via
tests/_boot_probe_roles_rules_subpage.py (pensé pour un but étroit, pas pour
vérifier le boot lui-même).

Sous-processus requis : le vrai boot pose des dizaines de monkeypatches
idempotents au niveau CLASSE (pensés pour un seul vrai bot par processus) qui
polluent le reste de la suite pytest partagée s'ils tournent dans le même
interpréteur — motif déjà établi par _boot_probe_roles_rules_subpage.py /
test_setup_roles_rules_subpage.py.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = Path(__file__).resolve().parent / "_boot_probe_smoke_test.py"


def _run_probe() -> dict:
    completed = subprocess.run(
        [sys.executable, str(PROBE)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, (
        f"la sonde de smoke-boot a échoué (code {completed.returncode}) :\n"
        f"stdout={completed.stdout!r}\nstderr={completed.stderr!r}"
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert lines, f"aucune sortie JSON de la sonde ; stderr={completed.stderr!r}"
    return json.loads(lines[-1])


_PROBE_RESULT: dict = {}


def _probe() -> dict:
    if not _PROBE_RESULT:
        _PROBE_RESULT.update(_run_probe())
    return _PROBE_RESULT


def test_le_bot_complet_boote_sans_aucune_extension_en_echec():
    result = _probe()
    assert "error" not in result, f"le boot a levé une exception :\n{result.get('traceback')}"
    assert result["extensions_failed"] == [], (
        f"{len(result['extensions_failed'])} extension(s) en échec au boot : "
        f"{result['extensions_failed']}"
    )
    assert result["extensions_loaded"] == result["extensions_expected"]


def test_le_bot_complet_expose_un_nombre_de_commandes_realiste():
    """Garde-fou grossier : un boot qui 'réussit' techniquement mais ne charge
    presque aucune commande (import cassé en amont, EXTENSIONS vidée par erreur)
    doit aussi être détecté."""
    result = _probe()
    assert result["commands"] > 200, (
        f"seulement {result['commands']} commande(s) enregistrée(s) après un boot complet "
        "-- probablement un chargement partiel silencieux"
    )
