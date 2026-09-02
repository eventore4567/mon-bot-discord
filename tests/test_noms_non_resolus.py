"""Aucun module ne doit utiliser un nom global qu'il n'a pas défini ni importé.

Cette classe d'erreur echappe aux tests : un module qui appelle
`stats_service.format_number` sans l'avoir importe ne leve qu'au moment ou la
ligne s'execute. Si ce chemin est rare — le resultat d'une manche de jeu, une
branche d'erreur — le NameError n'apparait qu'en production.

Trouve exactement comme cela pendant la refonte visuelle, dans
cogs/games_economy : le nouveau resultat de partie utilisait stats_service sans
import, et la suite restait verte.
"""
import pathlib
import sys
import unittest

RACINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "tools"))

from noms_non_resolus import verifier  # noqa: E402


class NomsGlobaux(unittest.TestCase):
    def test_aucun_nom_global_non_resolu(self):
        problemes = []
        for dossier in ("cogs", "utils"):
            for chemin in sorted((RACINE / dossier).glob("*.py")):
                problemes.extend(verifier(chemin))
        self.assertEqual(
            problemes, [],
            "noms utilisés sans définition ni import (NameError à l'exécution) :\n"
            + "\n".join(problemes[:20]),
        )

    def test_le_detecteur_voit_un_import_manquant(self):
        """Un detecteur qui ne detecte rien passerait aussi ce test sans cela."""
        import tempfile

        with tempfile.TemporaryDirectory() as dossier:
            faux = pathlib.Path(dossier) / "faux.py"
            faux.write_text("def f():\n    return stats_service.format_number(1)\n", encoding="utf-8")
            self.assertTrue(any("stats_service" in p for p in verifier(faux)))

    def test_le_detecteur_ne_crie_pas_sur_une_lambda(self):
        """`key=lambda row: row[0]` lie bien `row`."""
        import tempfile

        with tempfile.TemporaryDirectory() as dossier:
            bon = pathlib.Path(dossier) / "bon.py"
            bon.write_text("x = sorted([], key=lambda row: row[0])\n", encoding="utf-8")
            self.assertEqual(verifier(bon), [])


if __name__ == "__main__":
    unittest.main()
