"""Les configurations ne doivent plus demander d'identifiant a copier-coller.

Deux formulaires faisaient encore taper une valeur que Discord sait proposer :
le role d'un palier de niveau (« mentionnez-le avec @, ou collez son ID/nom ») et
le module a reinitialiser (« logs, bienvenue, notifications… »). Une faute de
frappe donnait « introuvable » sans dire quelles valeurs existaient.

discord.py 2.7 accepte un selecteur dans une modale via le composant Label. Ces
tests verifient que les deux formulaires en utilisent un, et qu'aucun autre
formulaire ne redemande un identifiant.
"""
import ast
import pathlib
import re
import unittest

import discord

RACINE = pathlib.Path(__file__).resolve().parent.parent

# Types de composants Discord, tels qu'ils apparaissent dans le JSON envoye.
LABEL = 18
TEXT_INPUT = 4
STRING_SELECT = 3
ROLE_SELECT = 6


def _composants(modale):
    return [
        (c["type"], c.get("component", {}).get("type"), c.get("label"))
        for c in modale.to_dict()["components"]
    ]


class RolesDeNiveau(unittest.TestCase):
    def test_le_role_se_choisit_dans_une_liste(self):
        from cogs.configuration import LevelRoleModal

        composants = _composants(LevelRoleModal(view=None))
        types = [interne for _, interne, _ in composants]
        self.assertIn(ROLE_SELECT, types, "le rôle devrait se choisir dans un RoleSelect")
        self.assertEqual(composants[0][1], TEXT_INPUT, "le niveau reste une saisie libre")
        for externe, _, _ in composants:
            self.assertEqual(externe, LABEL)


class ReinitialisationDeConfiguration(unittest.TestCase):
    def setUp(self):
        from cogs.setup_v2_completion import CIBLES_RESET, ResetConfigModal

        self.cibles = CIBLES_RESET
        self.modale = ResetConfigModal(owner=None)

    def test_le_module_se_choisit_dans_une_liste(self):
        composants = _composants(self.modale)
        self.assertEqual(composants[0][1], STRING_SELECT)
        self.assertEqual(composants[1][1], TEXT_INPUT, "la confirmation reste une saisie")

    def test_toutes_les_cibles_acceptees_sont_proposees(self):
        """Une option manquante rendrait une reinitialisation impossible depuis l'UI."""
        from cogs import setup_v2_core as core

        proposees = {cle for cle, _, _ in self.cibles}
        attendues = set(core.MODULES) | {"permissions", "all"}
        self.assertEqual(proposees, attendues)

    def test_chaque_option_dit_ce_qu_elle_efface(self):
        options = self.modale.to_dict()["components"][0]["component"]["options"]
        self.assertEqual(len(options), len(self.cibles))
        for option in options:
            with self.subTest(option=option["label"]):
                self.assertTrue(option.get("description"))

    def test_discord_accepte_le_nombre_d_options(self):
        self.assertLessEqual(len(self.cibles), 25)


class PlusAucuneSaisieDIdentifiant(unittest.TestCase):
    """Garde-fou : un nouveau formulaire ne doit pas reintroduire le probleme."""

    MOTIF = re.compile(r"(coll(ez|er).{0,20}\b(id|identifiant)\b|\bID\b\s*(du|de la|de l)\s*(rôle|salon|membre))", re.I)

    def test_aucun_libelle_ne_demande_un_identifiant(self):
        fautifs = []
        for fichier in sorted((RACINE / "cogs").glob("*.py")):
            try:
                arbre = ast.parse(fichier.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for noeud in ast.walk(arbre):
                if not isinstance(noeud, ast.Call):
                    continue
                if not ast.unparse(noeud.func).endswith("TextInput"):
                    continue
                for kw in noeud.keywords:
                    if kw.arg in ("label", "placeholder") and isinstance(kw.value, ast.Constant):
                        if self.MOTIF.search(str(kw.value.value)):
                            fautifs.append(f"{fichier.name}:{noeud.lineno} — {kw.value.value}")
        self.assertEqual(fautifs, [], "utilisez un RoleSelect / ChannelSelect / UserSelect :\n" + "\n".join(fautifs))


if __name__ == "__main__":
    unittest.main()
