"""Les fiches d'information doivent renseigner, pas seulement decorer.

`+info serveur` annoncait « 42 salons » sans dire de quels types, et affichait un
palier de boost sans dire combien il en manquait pour le suivant. `+info role`
listait les permissions en anglais (« manage guild ») et donnait une position
brute qui n'apprend rien : ce que l'on veut savoir, c'est si SentriX peut
attribuer ce role.

Aucune valeur affichee n'est inventee : tout vient de l'objet Discord.
"""
import unittest
from types import SimpleNamespace

import discord

from cogs import utility
from utils import access_matrix


class _Salon(SimpleNamespace):
    pass


def _guilde(**surcharges):
    base = dict(
        categories=[_Salon()] * 3,
        text_channels=[_Salon()] * 12,
        voice_channels=[_Salon()] * 4,
        forums=[],
        stage_channels=[],
        threads=[_Salon()] * 2,
        premium_tier=1,
        premium_subscription_count=5,
    )
    base.update(surcharges)
    return SimpleNamespace(**base)


class DetailDesSalons(unittest.TestCase):
    def test_donne_la_repartition_par_type(self):
        texte = utility._detail_salons(_guilde())
        self.assertIn("**12** textuels", texte)
        self.assertIn("**4** vocaux", texte)
        self.assertIn("**3** catégories", texte)
        self.assertIn("**2** fils actifs", texte)

    def test_tait_les_types_absents(self):
        """Afficher « 0 forums » serait du remplissage."""
        texte = utility._detail_salons(_guilde())
        self.assertNotIn("forums", texte)
        self.assertNotIn("conférences", texte)

    def test_serveur_vide(self):
        vide = _guilde(categories=[], text_channels=[], voice_channels=[], threads=[])
        self.assertEqual(utility._detail_salons(vide), "Aucun salon")


class MargeDeBoosts(unittest.TestCase):
    def test_annonce_ce_qui_manque_pour_le_palier_suivant(self):
        texte = utility._marge_boosts(_guilde(premium_tier=1, premium_subscription_count=5))
        self.assertIn("Encore **2**", texte)
        self.assertIn("palier 2", texte)

    def test_palier_maximal(self):
        texte = utility._marge_boosts(_guilde(premium_tier=3, premium_subscription_count=30))
        self.assertIn("maximal", texte)
        self.assertNotIn("Encore", texte)

    def test_seuil_atteint_mais_palier_pas_encore_applique(self):
        texte = utility._marge_boosts(_guilde(premium_tier=1, premium_subscription_count=7))
        self.assertNotIn("Encore", texte)

    def test_sans_aucun_boost(self):
        texte = utility._marge_boosts(_guilde(premium_tier=0, premium_subscription_count=0))
        self.assertIn("Aucun palier", texte)
        self.assertIn("Encore **2**", texte)


class LibellesDePermissions(unittest.TestCase):
    def test_toutes_les_permissions_discord_ont_un_libelle_francais(self):
        """Le repli produisait « Send messages » dans une interface francaise."""
        anglais = [
            nom
            for nom in sorted(discord.Permissions.VALID_FLAGS)
            if access_matrix.permission_label(nom).lower() == nom.replace("_", " ").lower()
        ]
        self.assertEqual(anglais, [])

    def test_les_permissions_sensibles_existent_vraiment(self):
        """Une faute de frappe dans la liste la rendrait silencieusement inutile."""
        for nom in access_matrix.PERMISSIONS_SENSIBLES:
            with self.subTest(permission=nom):
                self.assertIn(nom, discord.Permissions.VALID_FLAGS)

    def test_administrateur_est_traite_comme_sensible(self):
        self.assertIn("administrator", access_matrix.PERMISSIONS_SENSIBLES)


class ReglagesDeServeur(unittest.TestCase):
    def test_chaque_niveau_de_verification_est_traduit(self):
        for niveau in discord.VerificationLevel:
            with self.subTest(niveau=niveau.name):
                self.assertIn(niveau.name, utility.NIVEAUX_VERIFICATION)

    def test_chaque_filtre_de_contenu_est_traduit(self):
        for filtre in discord.ContentFilter:
            with self.subTest(filtre=filtre.name):
                self.assertIn(filtre.name, utility.FILTRES_CONTENU)


if __name__ == "__main__":
    unittest.main()
