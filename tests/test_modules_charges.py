"""10/11/2026 : la production journalise les fichiers jamais chargés (avant nettoyage)."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from utils import modules_charges as mc


def _arbo(tmp_path: Path) -> Path:
    for chemin in ("cogs/__init__.py", "cogs/actif.py", "cogs/mort.py", "cogs/pkg/__init__.py",
                   "utils/outil.py", "web/page.py", "cogs/__pycache__/x.py"):
        fichier = tmp_path / chemin
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_text("", encoding="utf-8")
    return tmp_path


def test_liste_les_fichiers_jamais_importes(tmp_path):
    racine = _arbo(tmp_path)
    assert mc.modules_sur_disque(racine) == {"cogs", "cogs.actif", "cogs.mort", "cogs.pkg", "utils.outil", "web.page"}
    assert mc.jamais_charges(racine, charges={"cogs.actif", "utils.outil"}) == ["cogs.mort", "cogs.pkg", "web.page"]


def test_les_lignes_de_journal_restent_courtes():
    noms = [f"cogs.module_{i:03d}" for i in range(300)]
    lignes = mc._lignes(noms, taille=200)
    assert all(len(l) <= 200 for l in lignes)
    assert ", ".join(lignes).split(", ") == noms


def test_le_constat_est_pose_une_seule_fois_et_journalise(caplog):
    async def scenario():
        bot = SimpleNamespace()
        mc.installer(bot, delai=0)
        mc.installer(bot, delai=0)
        await asyncio.sleep(0.05)

    with caplog.at_level("INFO", logger="bot.modules-charges"):
        asyncio.run(scenario())
    assert sum("FICHIERS JAMAIS CHARGÉS :" in r.message for r in caplog.records) == 1


def test_installe_au_demarrage():
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert "modules_charges.installer(self)" in source
