"""Anti-pub : les offres de produits ou services illégaux (26/11/2026).

Jayden : « que l'anti-pub bloque aussi le criminel ». Une offre ou demande
d'achat ET un produit illicite sont nécessaires : un mot seul ne bloque jamais.
"""
import os

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.automod import _scam_hit  # noqa: E402

BLOQUES = [
    "je vends de la coke dm moi",
    "vente weed livraison paris",
    "qui vend un glock ?",
    "dispo faux billets prix en mp",
    "selling cvv dm me",
    "10e le g de beuh",
    "je fais des dox mp moi pour les tarifs",
    "Je V3nds de la C0KE, DM moi",
    # Revue Codex (PR #730)
    "10 € le g de beuh",
    "Je vends une fausse carte d'identité",
    "Je vends une fausse carte d’identité",
    "vends résine 10g pochon dispo",
    "je vends une arme calibre 9 mm sans papiers",
]
LAISSES = [
    "la coke dans le film scarface",
    "j ai un glock dans valorant",
    "je vends mon velo",
    "tu es un criminel",
    "le prix du shit a augmenté selon le journal",
    "this is shit dm me later",
    "le livre des armes de la guerre",
    "ddos sur le serveur hier",
    "dispo pour une partie ?",
    "le crack de ma vitre",
    "je cherche à acheter un jeu",
    "qui veut jouer a la guerre des armes ?",
    # Revue Codex (PR #730) : sens ordinaires
    "Je vends des figurines en résine",
    "Je vends un vase en cristal",
    "je vends un pistolet à colle, dm moi",
    "vends nerf gun dispo",
    "vente de lean manufacturing en formation",
]


@pytest.mark.parametrize("texte", BLOQUES)
def test_offre_illicite_bloquee(texte):
    assert (_scam_hit(texte) or "").startswith("vente illicite"), texte


@pytest.mark.parametrize("texte", LAISSES)
def test_mot_seul_ou_contexte_anodin_laisse(texte):
    assert _scam_hit(texte) is None, texte
