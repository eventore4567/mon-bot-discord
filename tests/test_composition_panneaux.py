"""La composition des panneaux : bannière en tête, sections, pas de badge ALT.

Le critère n'est plus « la commande utilise-t-elle le design system » mais
« la composition a-t-elle changé ». Ces tests portent donc sur la STRUCTURE
produite, pas sur les couleurs.
"""
import ast
import pathlib
import unittest

import discord

import config
from utils import sentrix_panels as panels

RACINE = pathlib.Path(__file__).resolve().parent.parent

# Types de composants Discord.
ACTION_ROW, BOUTON, MENU, SECTION = 1, 2, 3, 9
TEXTE, VIGNETTE, GALERIE, FILET, CONTENEUR = 10, 11, 12, 14, 17


def _aplatir(items, sortie=None):
    sortie = [] if sortie is None else sortie
    for item in items or ():
        sortie.append(item)
        for cle in ("components", "accessory"):
            valeur = item.get(cle)
            if isinstance(valeur, list):
                _aplatir(valeur, sortie)
            elif isinstance(valeur, dict):
                _aplatir([valeur], sortie)
    return sortie


class StructureDUnPanneau(unittest.TestCase):
    def setUp(self):
        self.panneau = panels.Panneau(
            titre="SentriX — Test",
            sous_titre="Résumé court",
            kind="danger",
            vignette="https://example.invalid/a.png",
            sections=[
                panels.Section("Première", [panels.Ligne("Clé", "Valeur", indice="Un indice")]),
                panels.Section("Seconde", [panels.Ligne("Nombre", "42")], aligne=True),
            ],
            boutons=[panels.Bouton("Agir", custom_id="x")],
            pied="SentriX • Test",
        )
        self.plat = _aplatir(self.panneau.to_components())

    def test_la_banniere_est_le_premier_element(self):
        """Un embed ne peut pas faire cela : set_image place l'image SOUS les champs."""
        conteneur = self.panneau.to_components()[0]
        self.assertEqual(conteneur["type"], CONTENEUR)
        self.assertEqual(conteneur["components"][0]["type"], GALERIE)

    def test_la_banniere_part_dans_le_meme_message(self):
        galerie = next(i for i in self.plat if i["type"] == GALERIE)
        cible = galerie["items"][0]["media"]["url"]
        joints = [f.filename for f in self.panneau.fichiers()]
        self.assertTrue(cible.startswith("attachment://"))
        self.assertIn(cible.removeprefix("attachment://"), joints)

    def test_la_banniere_suit_l_intention(self):
        self.assertEqual([f.filename for f in self.panneau.fichiers()], ["banner_error.webp"])
        self.assertEqual(self.panneau.to_components()[0]["accent_color"], config.COLOR_ERROR)

    def test_chaque_section_est_precedee_d_un_filet(self):
        types = [i["type"] for i in self.panneau.to_components()[0]["components"]]
        sections = [i for i in self.plat if i["type"] == TEXTE and str(i.get("content", "")).startswith("### ")]
        self.assertEqual(len(sections), 2)
        self.assertGreaterEqual(types.count(FILET), 2)

    def test_le_mode_aligne_utilise_un_bloc_de_code(self):
        """Discord rend en police proportionnelle : hors bloc de code, rien ne s'aligne."""
        aligne = next(
            i for i in self.plat
            if i["type"] == TEXTE and "SECONDE" in str(i.get("content", ""))
        )
        self.assertIn("```", aligne["content"])

    def test_les_indices_sont_en_petit(self):
        texte = panels.texte_complet(self.panneau)
        self.assertIn("-# Un indice", texte)

    def test_les_boutons_sont_dans_le_conteneur(self):
        """Hors du conteneur, ils perdent l'accent de couleur du panneau."""
        conteneur = self.panneau.to_components()[0]
        rangees = [i for i in conteneur["components"] if i["type"] == ACTION_ROW]
        self.assertTrue(rangees)
        self.assertTrue(any(c["type"] == BOUTON for c in rangees[0]["components"]))


class PasDeBadgeAlt(unittest.TestCase):
    """Une image construite avec description= affiche « ALT » par-dessus.

    Le defaut est deja revenu deux fois dans ce depot : une fois sur la banniere
    des journaux, une fois sur la vignette du panneau premium. D'ou ce garde-fou.
    """

    CIBLES = ("Thumbnail", "MediaGallery", "add_item")

    def test_aucune_image_ne_porte_de_description(self):
        fautifs = []
        for dossier in ("cogs", "utils"):
            for chemin in sorted((RACINE / dossier).glob("*.py")):
                try:
                    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
                except SyntaxError:
                    continue
                for noeud in ast.walk(arbre):
                    if not isinstance(noeud, ast.Call):
                        continue
                    cible = ast.unparse(noeud.func)
                    if not cible.endswith(("Thumbnail", "MediaGallery")) and not (
                        cible.endswith("add_item")
                        and any(k.arg == "media" for k in noeud.keywords)
                    ):
                        continue
                    if any(k.arg == "description" for k in noeud.keywords):
                        fautifs.append(f"{chemin.name}:{noeud.lineno} — {cible}")
        self.assertEqual(
            fautifs, [],
            "description= sur une image affiche un badge « ALT » par-dessus :\n"
            + "\n".join(fautifs),
        )


class ContrainteComponentsV2(unittest.TestCase):
    def test_envoyer_refuse_un_content(self):
        """Discord repond 400 si un message Components V2 porte un content.

        Le ping de +userinfo passait justement par la. La garde evite qu'une
        commande reintroduise l'erreur sans comprendre pourquoi elle echoue.
        """
        import inspect

        source = inspect.getsource(panels.envoyer)
        self.assertIn('kwargs.pop("content", None)', source)

    def test_les_vues_composees_exposent_fichiers(self):
        """panels.envoyer joint la banniere via ce contrat : sans lui, image morte."""
        from cogs.help import VueAide
        from cogs.premium_ui_v81 import PremiumEmbedView

        for classe in (panels.Panneau, VueAide, PremiumEmbedView):
            with self.subTest(vue=classe.__name__):
                self.assertTrue(callable(getattr(classe, "fichiers", None)))


if __name__ == "__main__":
    unittest.main()
