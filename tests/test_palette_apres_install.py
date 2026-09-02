"""La palette doit rester unique APRES sentrix_runtime.install().

Les autres tests comparent les constantes des modules telles qu'importees. Or
`sentrix_runtime.install()` reassigne au demarrage `utils.embeds.COLOR_*`,
`utils.embeds._base` et `utils.design_system.create_embed` : ce que Discord affiche
n'est donc pas ce que ces tests mesurent. C'est cet angle mort qui a laisse coexister
trois violets et deux verts pour la meme intention.

`install()` est global et irreversible (garde `_INSTALLED`), et l'appeler ici ferait
echouer les tests qui s'attendent a l'etat non installe. La mesure se fait donc dans
un sous-processus dedie, qui reproduit l'ordre d'un vrai demarrage.
"""
import json
import pathlib
import subprocess
import sys
import unittest

RACINE = pathlib.Path(__file__).resolve().parent.parent

SONDE = r"""
import json, os, sys
os.environ.setdefault("DISCORD_TOKEN", "x")
sys.path.insert(0, %r)
import config
from utils import design_system, embeds, sentrix_runtime, sentrix_visual_cleanup

sentrix_runtime.install()

def couleur(embed):
    return embed.colour.value

def barre(embed):
    return (embed.description or "").startswith("━")

print(json.dumps({
    "config": {
        "success": config.COLOR_SUCCESS, "danger": config.COLOR_ERROR,
        "warning": config.COLOR_WARNING, "info": config.COLOR_INFO,
        "neutral": config.COLOR_NEUTRAL, "brand": config.COLOR_BRAND,
    },
    "embeds_constantes": {
        "success": embeds.COLOR_SUCCESS, "danger": embeds.COLOR_DANGER,
        "warning": embeds.COLOR_WARNING, "info": embeds.COLOR_INFO,
        "neutral": embeds.COLOR_NEUTRAL, "brand": embeds.COLOR_BRAND_UI,
    },
    "rendu_embeds": {
        "success": couleur(embeds.success("Corps")),
        "danger": couleur(embeds.error("Corps")),
        "warning": couleur(embeds.warning("Corps")),
    },
    "rendu_design_system": {
        "success": couleur(design_system.success_embed("Corps")),
        "danger": couleur(design_system.error_embed("Corps")),
        "warning": couleur(design_system.warning_embed("Corps")),
    },
    "barre_design_system": {
        nom: barre(getattr(design_system, nom)("Corps"))
        for nom in ("success_embed", "error_embed", "warning_embed", "info_embed")
    },
    "categories": {
        "moderation": couleur(design_system.category_embed("moderation", title="T", description="C")),
        "economy": couleur(design_system.category_embed("economy", title="T", description="C")),
        "moderation_attendue": design_system.COLORS.moderation,
        "barre": barre(design_system.category_embed("moderation", title="T", description="C")),
    },
    "copies_locales": {
        "runtime_success": sentrix_runtime.COLOR_SUCCESS,
        "runtime_warning": sentrix_runtime.COLOR_WARNING,
        "runtime_neutral": sentrix_runtime.COLOR_NEUTRAL,
        "runtime_system": sentrix_runtime.COLOR_SYSTEM,
        "cleanup_success": sentrix_visual_cleanup.COLOR_SUCCESS,
        "cleanup_warning": sentrix_visual_cleanup.COLOR_WARNING,
    },
}))
""" % (str(RACINE),)


def _mesure():
    sortie = subprocess.run(
        [sys.executable, "-c", SONDE], capture_output=True, text=True, cwd=str(RACINE), timeout=120
    )
    if sortie.returncode != 0:
        raise AssertionError(f"la sonde post-install a echoue :\n{sortie.stderr[-2000:]}")
    return json.loads(sortie.stdout.strip().splitlines()[-1])


class PaletteApresInstall(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _mesure()

    def test_embeds_expose_la_palette_de_config(self):
        self.assertEqual(self.m["embeds_constantes"], self.m["config"])

    def test_les_deux_renderers_donnent_la_meme_couleur(self):
        """Un succes rendu par embeds et par design_system doit etre le meme vert."""
        for intention in ("success", "danger", "warning"):
            with self.subTest(intention=intention):
                self.assertEqual(
                    self.m["rendu_embeds"][intention],
                    self.m["rendu_design_system"][intention],
                )
                self.assertEqual(
                    self.m["rendu_embeds"][intention], self.m["config"][intention]
                )

    def test_design_system_porte_la_barre_d_identite(self):
        """124 commandes passaient par design_system sans la barre que les autres ont."""
        for nom, presente in self.m["barre_design_system"].items():
            with self.subTest(fabrique=nom):
                self.assertTrue(presente)

    def test_les_teintes_de_categorie_survivent(self):
        """Une teinte de categorie est une identite voulue, pas un etat : elle reste."""
        cat = self.m["categories"]
        self.assertEqual(cat["moderation"], cat["moderation_attendue"])
        self.assertNotEqual(cat["moderation"], cat["economy"])
        self.assertTrue(cat["barre"])

    def test_aucun_module_ne_redefinit_une_teinte_semantique(self):
        """Toute copie locale finit par diverger. On verifie qu'il n'y en a plus."""
        c, copies = self.m["config"], self.m["copies_locales"]
        self.assertEqual(copies["runtime_success"], c["success"])
        self.assertEqual(copies["runtime_warning"], c["warning"])
        self.assertEqual(copies["runtime_neutral"], c["neutral"])
        self.assertEqual(copies["runtime_system"], c["brand"])
        self.assertEqual(copies["cleanup_success"], c["success"])
        self.assertEqual(copies["cleanup_warning"], c["warning"])


if __name__ == "__main__":
    unittest.main()
