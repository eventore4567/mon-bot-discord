"""Les messages d'erreur suivent la palette unique, et aucun chemin ne reste muet.

Une validation de production a montre que les embeds d'erreur sortaient encore a
l'ANCIENNE palette : cogs/final_error_embed_v5 figeait 0xED4245 et 0xF0B232 en dur.
Comme ce module rend tous les refus, tous les cooldowns et toutes les erreurs
internes du bot, chaque message d'erreur contredisait le reste de l'interface.

La porte de couverture UI ne pouvait pas le voir : elle verifie les COMMANDES, et
un gestionnaire d'erreur n'en est pas une. D'ou ces tests.
"""
import json
import pathlib
import subprocess
import sys
import unittest

import config
from cogs import final_error_embed_v5 as erreurs
from utils import embeds as sx, premium_style, sentrix_panels as panels, visual_v5

RACINE = pathlib.Path(__file__).resolve().parent.parent

# Teintes d'avant l'unification. Elles restent reconnues, jamais emises.
ANCIENNES = {"danger": 0xED4245, "warning": 0xF0B232, "success": 0x57F287, "marque": 0x5847EB}


class PaletteDesErreurs(unittest.TestCase):
    def test_le_module_d_erreur_suit_la_source_unique(self):
        self.assertEqual(erreurs.ERROR_COLOR, config.COLOR_ERROR)
        self.assertEqual(erreurs.WARNING_COLOR, config.COLOR_WARNING)

    def test_il_n_emet_plus_les_anciennes_teintes(self):
        self.assertNotEqual(erreurs.ERROR_COLOR, ANCIENNES["danger"])
        self.assertNotEqual(erreurs.WARNING_COLOR, ANCIENNES["warning"])

    def test_les_panneaux_portent_l_identite(self):
        for titre, avertissement, attendue in (
            ("Erreur de commande", False, config.COLOR_ERROR),
            ("Commande en cooldown", True, config.COLOR_WARNING),
        ):
            with self.subTest(panneau=titre):
                panneau = erreurs._panel(titre, "Détail.", warning=avertissement)
                self.assertEqual(panneau.colour.value, attendue)
                self.assertTrue((panneau.description or "").startswith(sx.BAR[:8]))
                self.assertTrue((panneau.footer.text or "").startswith("SentriX"))
                self.assertIsNone(panneau.image.url)


class PanneauDeComposant(unittest.TestCase):
    """Boutons, menus et formulaires n'affichaient rien : discord.ui journalise."""

    def test_le_panneau_nomme_le_bouton_en_cause(self):
        class Faux:
            label = "Confirmer"
        self.assertIn("Confirmer", panels.texte_complet(erreurs._component_error_panel(Faux())))

    def test_il_fonctionne_sans_libelle(self):
        self.assertIn("cette action", panels.texte_complet(erreurs._component_error_panel(None)))

    def test_il_dit_que_rien_n_a_ete_enregistre(self):
        """Sans cette information, le membre ne sait pas s'il doit recommencer."""
        texte = panels.texte_complet(erreurs._component_error_panel(None)).casefold()
        self.assertIn("aucune modification", texte)

    def test_il_a_l_identite_des_autres_erreurs(self):
        """Banniere en tete, accent rouge, sections : comme tous les autres."""
        panneau = erreurs._component_error_panel(None)
        composants = panneau.to_components()
        self.assertEqual(composants[0]["accent_color"], config.COLOR_ERROR)
        texte = panels.texte_complet(panneau)
        self.assertIn("## Action interrompue", texte)
        self.assertGreaterEqual(texte.count("### "), 2, "il faut au moins deux sections")
        self.assertIn("SentriX", texte)
        self.assertEqual([f.filename for f in panneau.fichiers()], ["banner_error.webp"])


class AutresRenderers(unittest.TestCase):
    def test_premium_style_emet_la_palette_unique(self):
        for cle, attendue in (
            ("success", config.COLOR_SUCCESS), ("danger", config.COLOR_ERROR),
            ("warning", config.COLOR_WARNING), ("info", config.COLOR_INFO),
            ("brand", config.COLOR_BRAND), ("neutral", config.COLOR_NEUTRAL),
        ):
            with self.subTest(intention=cle):
                self.assertEqual(premium_style.COLORS[cle], attendue)

    def test_premium_style_reconnait_encore_les_anciennes(self):
        """Des embeds construits ailleurs portent encore les vieilles teintes."""
        for valeur in (ANCIENNES["danger"], ANCIENNES["warning"], ANCIENNES["success"]):
            with self.subTest(couleur=hex(valeur)):
                self.assertIn(valeur, premium_style.SYSTEM_COLOURS)

    def test_premium_style_reconnait_aussi_les_nouvelles(self):
        for valeur in (config.COLOR_ERROR, config.COLOR_WARNING, config.COLOR_SUCCESS):
            with self.subTest(couleur=hex(valeur)):
                self.assertIn(valeur, premium_style.SYSTEM_COLOURS)

    def test_les_categories_gardent_leur_teinte(self):
        """Une couleur de categorie est une identite, pas un etat : elle ne bouge pas."""
        self.assertNotEqual(premium_style.COLORS["tickets"], config.COLOR_INFO)
        self.assertNotEqual(premium_style.COLORS["economy"], config.COLOR_WARNING)

    def test_le_theme_officiel_porte_la_palette_officielle(self):
        officiel = visual_v5.THEME_PRESETS["sentrix"]
        self.assertEqual(officiel["primary_color"], config.COLOR_BRAND)
        self.assertEqual(officiel["success_color"], config.COLOR_SUCCESS)
        self.assertEqual(officiel["danger_color"], config.COLOR_ERROR)

    def test_les_autres_themes_restent_distincts(self):
        """« cyber » et les autres sont des choix esthetiques, pas l'identite."""
        self.assertNotEqual(
            visual_v5.THEME_PRESETS["cyber"]["primary_color"], config.COLOR_BRAND
        )


SONDE = r"""
import json, os, sys
os.environ.setdefault("DISCORD_TOKEN", "x")
sys.path.insert(0, %r)
import discord
from discord.ext import commands
from cogs import final_error_embed_v5 as erreurs

bot = commands.Bot(command_prefix="+", intents=discord.Intents.none())
erreurs.install(bot)
print(json.dumps({
    "vue": discord.ui.View.on_error.__module__,
    "modal": discord.ui.Modal.on_error.__module__,
    "commande": getattr(bot.on_command_error, "__module__", ""),
    "slash": bot.tree.on_error.__module__,
}))
""" % (str(RACINE),)


class BranchementApresInstall(unittest.TestCase):
    """install() patche des classes globales : la mesure se fait a l'ecart."""

    def test_les_quatre_chemins_sont_branches(self):
        sortie = subprocess.run(
            [sys.executable, "-c", SONDE], capture_output=True, text=True,
            cwd=str(RACINE), timeout=120,
        )
        self.assertEqual(sortie.returncode, 0, sortie.stderr[-1500:])
        branches = json.loads(sortie.stdout.strip().splitlines()[-1])
        for chemin in ("vue", "modal", "slash"):
            with self.subTest(chemin=chemin):
                self.assertIn("final_error_embed_v5", branches[chemin],
                              f"{chemin} n'est pas branché : {branches[chemin]}")


if __name__ == "__main__":
    unittest.main()
