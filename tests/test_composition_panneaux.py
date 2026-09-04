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


class PontDepuisEmbed(unittest.TestCase):
    """Beaucoup de reponses SentriX sont produites par une CHAINE de modules.

    Douze couches enrichissent le centre de configuration, deux enrichissent les
    sanctions. Porter chaque maillon vers un nouveau contrat serait autant
    d'occasions de casser ce qui marche ; convertir le resultat final n'en est
    aucune. Ce pont est donc structurel, pas un raccourci.
    """

    def _embed(self):
        import discord as d

        embed = d.Embed(title="Dossier #42 — Bannissement", description="━━━━━━━━━━\nRésumé")
        embed.add_field(name="👤 Membre", value="<@1>", inline=True)
        embed.add_field(name="📝 Raison", value="Spam massif", inline=False)
        embed.add_field(name="Vide", value="", inline=False)
        embed.set_footer(text="SentriX")
        return embed

    def test_un_champ_devient_une_section(self):
        """Le mode compact (par defaut) regroupe les champs courts : ce test porte
        specifiquement sur le pont champ -> section, donc compact=False."""
        panneau = panels.depuis_embed(self._embed(), kind="moderation", compact=False)
        titres = [
            t.split("\n")[0] for t in
            [i.get("content", "") for i in _aplatir(panneau.to_components())]
            if t.startswith("### ")
        ]
        self.assertEqual(len(titres), 2, "un champ vide ne doit pas créer de section")

    def test_les_emojis_de_tete_sont_retires(self):
        """Le chevron et le filet marquent deja la section ; l'emoji fait du bruit."""
        texte = panels.texte_complet(panels.depuis_embed(self._embed(), kind="moderation", compact=False))
        self.assertIn("### ◢ MEMBRE", texte)
        self.assertNotIn("👤", texte)

    def test_la_barre_dessinee_disparait(self):
        """Le panneau a de vrais filets : la barre en caracteres ferait doublon."""
        texte = panels.texte_complet(panels.depuis_embed(self._embed(), kind="moderation"))
        self.assertNotIn("━━━━━━", texte)
        self.assertIn("Résumé", texte)

    def test_la_banniere_suit_le_domaine_demande(self):
        panneau = panels.depuis_embed(self._embed(), kind="moderation")
        self.assertEqual([f.filename for f in panneau.fichiers()], ["banner_moderation.webp"])

    def test_compact_regroupe_les_champs_dans_une_seule_section(self):
        """Un dossier de sanction a sept champs courts : chacun avec son propre
        grand titre et son propre filet rendait la fiche disproportionnee. En
        mode compact, un seul "### ◢ RÉSUMÉ" porte tous les champs, une ligne
        chacun."""
        texte = panels.texte_complet(panels.depuis_embed(self._embed(), kind="moderation", compact=True))
        self.assertEqual(texte.count("### "), 1)
        self.assertIn("### ◢ RÉSUMÉ", texte)
        self.assertIn("**Membre** · <@1>", texte)
        self.assertIn("**Raison** · Spam massif", texte)

    def test_compact_tient_sur_moins_de_lignes_que_le_rendu_normal(self):
        compact = panels.texte_complet(panels.depuis_embed(self._embed(), kind="moderation", compact=True))
        normal = panels.texte_complet(panels.depuis_embed(self._embed(), kind="moderation", compact=False))
        self.assertLess(len(compact.splitlines()), len(normal.splitlines()))

    def test_compact_sans_champs_ne_plante_pas(self):
        embed = discord.Embed(title="Rien à voir")
        panneau = panels.depuis_embed(embed, compact=True)
        self.assertIsInstance(panneau, panels.Panneau)

    def test_compact_est_le_reglage_par_defaut(self):
        """toutes les commandes passent par depuis_embed() sans jamais preciser
        compact= : c'est donc bien le defaut qui doit produire le rendu court."""
        avec_defaut = panels.texte_complet(panels.depuis_embed(self._embed(), kind="moderation"))
        explicite = panels.texte_complet(panels.depuis_embed(self._embed(), kind="moderation", compact=True))
        self.assertEqual(avec_defaut, explicite)

    def test_compact_ne_tronque_jamais_un_champ_trop_long_pour_une_ligne(self):
        """Le mode compact ne doit JAMAIS perdre d'information : un champ trop
        long ou multi-lignes pour tenir sur une ligne garde sa propre section
        complete au lieu d'etre tronque dans le Résumé."""
        long_texte = "Ligne 1\nLigne 2 avec beaucoup de details sur ce qui s'est passe exactement."
        embed = discord.Embed(title="Dossier")
        embed.add_field(name="Court", value="ok", inline=True)
        embed.add_field(name="Long détail", value=long_texte, inline=False)
        texte = panels.texte_complet(panels.depuis_embed(embed, kind="moderation"))
        self.assertIn("### ◢ RÉSUMÉ", texte)
        self.assertIn("**Court** · ok", texte)
        self.assertIn("### ◢ LONG DÉTAIL", texte)
        self.assertIn(long_texte, texte)

    def test_une_sanction_n_est_pas_peinte_en_vert(self):
        """« Membre banni » n'est pas une bonne nouvelle : c'est un acte de modération."""
        panneau = panels.depuis_embed(self._embed(), kind="moderation")
        accent = panneau.to_components()[0]["accent_color"]
        self.assertNotEqual(accent, config.COLOR_SUCCESS)
        self.assertEqual(accent, panels.INTENTIONS["moderation"][0])


class Confirmations(unittest.TestCase):
    """Trois moments d'une confirmation etaient muets."""

    def setUp(self):
        from utils.helpers import ConfirmView

        self.vue = ConfirmView(author_id=1, timeout=1)

    def test_un_clic_fige_les_boutons(self):
        """Une decision prise ne doit plus paraitre cliquable."""
        self.vue._figer()
        self.assertTrue(all(getattr(e, "disabled", False) for e in self.vue.children))

    def test_l_expiration_vaut_un_refus(self):
        """Le silence n'est pas un accord : value doit valoir False, jamais None."""
        import asyncio

        asyncio.run(self.vue.on_timeout())
        self.assertIs(self.vue.value, False)
        self.assertTrue(all(getattr(e, "disabled", False) for e in self.vue.children))

    def test_l_expiration_sans_message_ne_leve_pas(self):
        """message est facultatif : les appelants historiques ne le renseignent pas."""
        import asyncio

        self.vue.message = None
        asyncio.run(self.vue.on_timeout())  # ne doit pas lever

    def test_le_refus_explique_quoi_faire(self):
        """« Seule la personne à l'origine peut confirmer » ne disait pas la suite."""
        import inspect
        from utils.helpers import ConfirmView

        source = inspect.getsource(ConfirmView.interaction_check)
        self.assertIn("Lancez la commande vous-même", source)
        self.assertIn("panels.envoyer", source)


class RenduUnifie(unittest.TestCase):
    """Un seul rendu pour toutes les commandes.

    +profile, +serverinfo et +leaderboard passaient par un convertisseur
    parallele : titre sans chevrons, aucune banniere, et surtout aucune methode
    fichiers() alors que le code appelant l'invoque — les trois commandes
    levaient une AttributeError. Elles doivent produire exactement la meme
    typographie que les 521 autres.
    """

    def _embed(self):
        import discord

        embed = discord.Embed(title="Profil", description="Deux ans", colour=0x8B7AFF)
        embed.add_field(name="Niveau", value="42")
        embed.set_footer(text="SentriX")
        return embed

    def test_le_convertisseur_compact_produit_un_panneau(self):
        from cogs.premium_ui_v82 import PremiumEmbedViewV82

        vue = PremiumEmbedViewV82(self._embed(), compact=True)
        self.assertIsInstance(vue, panels.Panneau)
        # fichiers() est le contrat que panels.envoyer utilise pour joindre la
        # banniere : sans lui, l'appelant plante.
        self.assertTrue(vue.fichiers())

    def test_la_typographie_est_celle_de_tous_les_autres_panneaux(self):
        from cogs.premium_ui_v82 import PremiumEmbedViewV82

        rendu = panels.texte_complet(PremiumEmbedViewV82(self._embed(), compact=True))
        self.assertTrue(rendu.startswith("## "), rendu[:40])
        self.assertIn("### ◢ ", rendu)

    def test_le_mode_compact_tient_sur_moins_de_lignes(self):
        from cogs.premium_ui_v82 import PremiumEmbedViewV82

        import discord

        embed = discord.Embed(title="Profil")
        for i in range(6):
            embed.add_field(name=f"Champ {i}", value=str(i))
        compact = panels.texte_complet(PremiumEmbedViewV82(embed, compact=True))
        large = panels.texte_complet(PremiumEmbedViewV82(embed, compact=False))
        # C'est la seule raison d'etre du mode compact : six champs ne doivent
        # pas occuper douze lignes.
        self.assertLess(len(compact.splitlines()), len(large.splitlines()))
