"""10/11/2026 : réponses longues de l'IA dans une carte, courtes en texte."""
import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from utils import ai_presentation as p  # noqa: E402


def test_court_en_texte_long_en_carte():
    assert not p.doit_etre_en_carte("Salut ! Ça va et toi ?")
    assert p.doit_etre_en_carte("x" * 600)
    assert p.doit_etre_en_carte("\n".join(f"- point {i}" for i in range(7)))


def test_la_carte_est_coloree_et_signee():
    [vue] = p.cartes("Voici une explication détaillée.\n\n" + "texte " * 120)
    carte = vue.children[0]
    assert isinstance(carte, discord.ui.Container) and carte.accent_colour.value == p.COULEUR
    textes = [i.content for i in carte.children if isinstance(i, discord.ui.TextDisplay)]
    assert textes[0].startswith("Voici une explication") and textes[-1] == p.SIGNATURE


def test_tres_long_texte_en_plusieurs_cartes_sans_casser_le_code():
    texte = "Intro\n```python\n" + "print('ligne')\n" * 400 + "```\nFin"
    vues = p.cartes(texte)
    assert len(vues) > 1
    for vue in vues:
        contenu = "".join(i.content for i in vue.children[0].children if isinstance(i, discord.ui.TextDisplay))
        assert len(contenu) <= 4000
        assert contenu.count("```") % 2 == 0          # chaque bloc de code est refermé
    assert vues[-1].children[0].children[-1].content == p.SIGNATURE
