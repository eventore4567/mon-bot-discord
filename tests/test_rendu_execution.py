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
