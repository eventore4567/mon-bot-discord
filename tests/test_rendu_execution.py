"""La migration se constate par EXÉCUTION, pas par un marqueur dans du code partagé.

Deux fois pendant cette refonte, la porte statique a annoncé des chiffres faux :
un `panels.Section` présent dans un entonnoir commun décrit ce que le code PEUT
faire, pas ce qu'une commande donnée fait. Ce test verrouille l'autre approche.

Il ne relance pas les 536 commandes — le harnais charge tout le bot et prend une
minute. Il verrouille l'outil lui-même, là où les erreurs de jugement se logent.
"""
import pathlib
import sys
import unittest

import discord

RACINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "tools"))

import verif_execution as verif  # noqa: E402


class ClassementDesEnvois(unittest.TestCase):
    def test_un_panneau_avec_section_est_reconnu(self):
        from utils import sentrix_panels as panels

        vue = panels.Panneau(
            titre="T", sections=[panels.Section("S", [panels.Ligne("a", "b")])]
        )
        verdict, sections = verif._classer([{"voie": "ctx.send", "kwargs": {"view": vue}}])
        self.assertEqual(verdict, "panneau+sections")
        self.assertGreaterEqual(sections, 1)

    def test_un_panneau_sans_section_est_de_l_identite(self):
        from utils import sentrix_panels as panels

        vue = panels.Panneau(titre="T", sous_titre="Une phrase.")
        verdict, sections = verif._classer([{"voie": "ctx.send", "kwargs": {"view": vue}}])
        self.assertEqual(verdict, "panneau")
        self.assertEqual(sections, 0)

    def test_un_embed_reste_un_embed(self):
        import discord

        verdict, _ = verif._classer(
            [{"voie": "ctx.send", "kwargs": {"embed": discord.Embed(title="T")}}]
        )
        self.assertEqual(verdict, "embed")

    def test_un_journal_n_est_jamais_la_reponse(self):
        """Les journaux gardent leur format grand large : les compter comme la
        réponse d'une commande donnait un faux négatif sur +clear."""
        import discord

        verdict, _ = verif._classer(
            [{"voie": "channel.send", "kwargs": {"embed": discord.Embed(title="Journal")}}]
        )
        self.assertEqual(verdict, "aucun")

    def test_la_reponse_prime_sur_le_journal(self):
        import discord
        from utils import sentrix_panels as panels

        captures = [
            {"voie": "channel.send", "kwargs": {"embed": discord.Embed(title="Journal")}},
            {"voie": "ctx.send", "kwargs": {"view": panels.Panneau(titre="T")}},
        ]
        verdict, _ = verif._classer(captures)
        self.assertEqual(verdict, "panneau")


class SyntheseDArguments(unittest.TestCase):
    """Sans arguments synthétisés, 112 commandes restaient invérifiables."""

    def test_les_types_courants_sont_couverts(self):
        import discord

        class Ctx:
            author = "membre"
            channel = "salon"
            class guild:
                roles = ["role"]

        async def commande(self, ctx, membre: discord.Member, salon: discord.TextChannel,
                           role: discord.Role, texte: str, nombre: int):
            pass

        valeurs, manque = verif._arguments(commande, Ctx())
        self.assertEqual(manque, "")
        self.assertEqual(set(valeurs), {"membre", "salon", "role", "texte", "nombre"})

    def test_un_type_inconnu_est_signale_pas_devine(self):
        async def commande(self, ctx, piece: "discord.Attachment"):
            pass

        valeurs, manque = verif._arguments(commande, object())
        self.assertEqual(valeurs, {})
        self.assertIn("piece", manque)


if __name__ == "__main__":
    unittest.main()


def test_avatar_rend_un_panneau_avec_l_image_et_la_mention():
    """Regression : +avatar est reste en embed longtemps apres la migration.

    Le harnais d'execution echouait AVANT l'envoi (un faux Asset sans read()), et
    « aucun envoi » avait ete lu comme une limite de simulation plutot que comme
    une commande non migree. On verifie donc les trois promesses a la fois : c'est
    un panneau, il porte l'image, et la personne visee est toujours notifiable.
    """
    import ast

    source = (RACINE / "cogs" / "utility.py").read_text(encoding="utf-8")
    corps = next(
        ast.unparse(n)
        for n in ast.walk(ast.parse(source))
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "avatar"
    )
    assert "panels.envoyer" in corps
    assert "ctx.send" not in corps
    assert "mentionner=self._cible_a_notifier(ctx, membre)" in corps

    constructeur = next(
        ast.unparse(n)
        for n in ast.walk(ast.parse(source))
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "_panneau_avatar"
    )
    assert "image=url" in constructeur


def test_le_panneau_expose_une_image_de_contenu():
    from utils import sentrix_panels as panels

    panneau = panels.Panneau(titre="Avatar", kind="info", image="https://exemple/i.png")
    medias = [
        item
        for conteneur in panneau.children
        for item in getattr(conteneur, "children", ())
        if isinstance(item, discord.ui.MediaGallery)
    ]
    # Deux galeries : la banniere d'intention, puis l'image demandee.
    urls = [str(m.media.url) for galerie in medias for m in galerie.items]
    assert any("exemple/i.png" in u for u in urls), urls
