"""La porte de couverture UI ne doit pas regresser.

Le test ne relance pas l'analyse complete (elle charge tout le bot, ~30 s) : il
verifie l'outil sur des cas construits, la ou les erreurs de jugement se logent.
La mesure reelle se fait avec `python3 tools/ui_coverage_gate.py`.
"""
import ast
import json
import pathlib
import unittest

import sys

RACINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "tools"))
import ui_coverage_gate as porte  # noqa: E402


def _fns(source: str) -> dict:
    arbre = ast.parse(source)
    return {
        n.name: n
        for n in ast.walk(arbre)
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
    }


class DetectionDesChemins(unittest.TestCase):
    def test_reconnait_les_deux_renderers_canoniques(self):
        """embeds et design_system delegent au meme constructeur : les deux comptent."""
        self.assertIn("canonique", porte.chemins_trouves("embeds.success('ok')"))
        self.assertIn("canonique", porte.chemins_trouves("design_system.success_embed('ok')"))

    def test_reconnait_components_v2(self):
        """Un LayoutView porte sa propre identite : ce n'est pas un contournement."""
        self.assertIn("components_v2", porte.chemins_trouves("view = ui.LayoutView()"))

    def test_signale_un_embed_brut(self):
        self.assertIn("embed_brut", porte.chemins_trouves("discord.Embed(title='x')"))

    def test_les_exemptions_portent_toutes_une_raison(self):
        """Une exclusion sans justification ecrite finit par cacher une vraie dette."""
        for nom, _motifs, raison in porte.EXEMPTIONS:
            with self.subTest(exemption=nom):
                self.assertGreater(len(raison), 40, f"{nom} : raison trop vague")
        for commande, raison in porte.TEXTE_VOLONTAIRE.items():
            with self.subTest(commande=commande):
                self.assertGreater(len(raison), 20, f"{commande} : raison trop vague")


class SuiviDeLaDelegation(unittest.TestCase):
    """Le point qui rend la porte utile plutot que bruyante."""

    SOURCE = """
def rendre(titre):
    return design_system.create_embed(title=titre)

async def _fabrique(bot, titre):
    return rendre(titre)

async def _partage(self, ctx, nom):
    await ctx.send(embed=await _fabrique(self.bot, nom))

async def fishing(self, ctx):
    await self._run_solo(ctx, 'fishing')

async def _run_solo(self, ctx, nom):
    await self._partage(ctx, nom)

async def orpheline(self, ctx):
    await ctx.send('texte nu')
"""

    def setUp(self):
        self.fns = _fns(self.SOURCE)

    def test_suit_la_chaine_sur_plusieurs_sauts(self):
        """fishing -> _run_solo -> _partage -> _fabrique -> rendre.

        S'arreter au premier saut declarait a tort 13 commandes de jeu « sans rendu ».
        """
        self.assertIn("canonique", porte.suivre_delegation("fishing", self.fns))

    def test_ne_prete_pas_de_rendu_a_une_commande_qui_n_en_a_pas(self):
        self.assertNotIn("canonique", porte.suivre_delegation("orpheline", self.fns))

    def test_s_arrete_sur_un_cycle(self):
        """Deux fonctions qui s'appellent mutuellement ne doivent pas figer la porte."""
        fns = _fns("def a(): b()\ndef b(): a()\n")
        self.assertEqual(porte.suivre_delegation("a", fns), set())

    def test_respecte_la_profondeur_maximale(self):
        chaine = "\n".join(f"def n{i}(): n{i + 1}()" for i in range(12))
        chaine += "\ndef n12(): return embeds.success('ok')\n"
        self.assertNotIn("canonique", porte.suivre_delegation("n0", _fns(chaine)))


class FranchirLesModules(unittest.TestCase):
    """`+help` et `+diagnostic` rendent via une methode d'un AUTRE cog."""

    LOCAL = """
async def prefix_help_entry(ctx, commande=None):
    help_cog = bot.get_cog('SentriXHelp')
    await help_cog.send_help(ctx, commande)

async def orpheline(ctx):
    await ctx.send('texte nu')
"""
    # Ce que la porte connait du reste du depot : uniquement les noms definis une
    # seule fois. `send_help` puis `_home` reproduisent la vraie chaine de +help.
    GLOBALES = {
        "send_help": "async def send_help(self, target, query=None):\n    panel = _home(self.bot, target.author)\n    await target.send(embed=panel)",
        "_home": "def _home(bot, member):\n    return embeds.standard('Aide', 'Corps')",
    }

    def setUp(self):
        self.fns = _fns(self.LOCAL)

    def test_suit_l_appel_vers_un_autre_cog(self):
        trouves = porte.suivre_delegation("prefix_help_entry", self.fns, globales=self.GLOBALES)
        self.assertIn("canonique", trouves)

    def test_ne_franchit_pas_sans_index_global(self):
        """Sans la table des noms uniques, le saut n'a pas lieu : pas de devinette."""
        trouves = porte.suivre_delegation("prefix_help_entry", self.fns)
        self.assertNotIn("canonique", trouves)

    def test_un_nom_absent_de_l_index_n_est_pas_suivi(self):
        """L'index exclut les noms ambigus ; un homonyme ne doit rien conclure."""
        trouves = porte.suivre_delegation("orpheline", self.fns, globales=self.GLOBALES)
        self.assertNotIn("canonique", trouves)

    def test_le_module_local_reste_prioritaire(self):
        """Un nom defini localement ne doit pas etre lu depuis l'index global."""
        fns = _fns("def rendu():\n    pass\ndef commande():\n    rendu()\n")
        trouves = porte.suivre_delegation(
            "commande", fns, globales={"rendu": "def rendu():\n    return embeds.success('x')"}
        )
        self.assertNotIn("canonique", trouves)


class DetteDeReference(unittest.TestCase):
    def test_le_fichier_de_dette_existe_et_est_lisible(self):
        donnees = json.loads(porte.DETTE.read_text(encoding="utf-8"))
        self.assertIn("commandes", donnees)
        self.assertIn("_lisez_moi", donnees)

    def test_la_dette_ne_contient_pas_de_doublon(self):
        commandes = json.loads(porte.DETTE.read_text(encoding="utf-8"))["commandes"]
        self.assertEqual(len(commandes), len(set(commandes)))


if __name__ == "__main__":
    unittest.main()
