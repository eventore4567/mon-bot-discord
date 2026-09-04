"""La page /setup "Rôles — Règles & CAPTCHA" (cogs/control_center_v3.py, category="roles",
subpage="rules") était injoignable en conditions réelles et, une fois atteinte de force,
affichait un titre tronqué :

1. Le sélecteur de catégorie réellement posé en ligne 0 par la VRAIE chaîne de boot
   n'est ni V3CategorySelect ni _V4CategorySelectCompat mais
   cogs/setup_polish_v70.py::V70PageSelect -- render_v70() retire *tout* enfant en ligne
   0 à chaque render() (y compris les sélecteurs posés par les couches précédentes) et
   le remplace par sa propre instance. Or V70PageSelect ne construisait ses options qu'à
   partir de setup_ui.CATEGORIES : les entrées "roles_rules"/"roles_panel" (et
   "security_verification") posées par les couches antérieures n'atteignaient donc
   jamais l'utilisateur -- ces sous-pages étaient invisibles et injoignables dans
   Discord, quel que soit le contenu correct de leurs propres callbacks.

2. Même en forçant category="roles"/_v3_subpage="rules" (donc en contournant le bug
   ci-dessus), le titre de sous-page ("Rôles — Règles & CAPTCHA") calculé par
   _v3_build_embed était perdu : deux couches ULTÉRIEURES de la chaîne de rendu
   (cogs/setup_oxyde_v69.py::_build_page puis cogs/setup_polish_v70.py::_generic_page)
   RECONSTRUISENT entièrement l'embed à partir de self.category seul (_label(page_id)),
   sans connaître la notion de sous-page -- un bug préexistant qui touchait déjà
   silencieusement "Rôles — Panel de choix" avant ce correctif.

La vérification passe par un VRAI boot complet (tous les cogs réels, tous les
monkeypatches de finalize_runtime()) plutôt que d'appeler directement _v3_build_embed
en isolation ou d'instancier un sélecteur choisi à la main : category/_v3_subpage
réglés "à la main" sans boot complet rendaient la bonne page alors que personne, dans
Discord, ne pouvait réellement l'atteindre -- une vérification en isolation avait donc
laissé passer les deux bugs la première fois.

Ce boot complet tourne dans tests/_boot_probe_roles_rules_subpage.py, un SOUS-PROCESSUS
séparé plutôt qu'un import direct ici : charger les ~300 extensions réelles applique des
monkeypatches globaux non pensés pour cohabiter avec le reste de la suite dans le même
interpréteur (la plupart utilisent une garde d'idempotence par processus). La première
version de ce test bootait dans le même processus que pytest et cassait cinq tests sans
rapport dans tests/test_visual_brand_v2.py en court-circuitant leur propre install().
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = Path(__file__).resolve().parent / "_boot_probe_roles_rules_subpage.py"


def _run_probe() -> dict:
    completed = subprocess.run(
        [sys.executable, str(PROBE)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, (
        f"la sonde a échoué (code {completed.returncode}) :\n"
        f"stdout={completed.stdout!r}\nstderr={completed.stderr!r}"
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert lines, f"aucune sortie JSON de la sonde ; stderr={completed.stderr!r}"
    data = json.loads(lines[-1])
    assert "error" not in data, f"la sonde a levé une exception :\n{data.get('traceback')}"
    return data


_PROBE_RESULT: dict = {}


def _probe() -> dict:
    if not _PROBE_RESULT:
        _PROBE_RESULT.update(_run_probe())
    return _PROBE_RESULT


def test_rules_subpage_title_survives_the_full_render_chain():
    data = _probe()
    assert data["rules_title"] == "SentriX — Rôles — Règles & CAPTCHA"
    assert {"salon des règles", "rôle donné", "captcha", "tentatives max."} <= set(data["rules_fields"])


def test_roles_panel_subpage_title_also_survives_the_full_render_chain():
    """Régression : le même bug de titre touchait déjà l'ancienne page panel de rôles."""
    data = _probe()
    assert data["panel_title"] == "SentriX — Rôles — Panel de choix"


def test_v70_page_select_offers_and_routes_the_roles_rules_option():
    """Le VRAI sélecteur de ligne 0 en production (V70PageSelect, qui écrase tous les
    autres à chaque render()) doit à la fois PROPOSER l'option "roles_rules" et la
    router vers category="roles"/_v3_subpage="rules" -- sinon la page CAPTCHA reste
    invisible et injoignable dans Discord même si tout son rendu est par ailleurs correct.
    """
    data = _probe()
    assert "roles_rules" in data["select_options"]
    assert data["select_refresh_called"] is True
    assert data["after_click_category"] == "roles"
    assert data["after_click_subpage"] == "rules"
