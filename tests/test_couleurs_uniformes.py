"""11/11/2026 : le même domaine changeait de couleur selon l'écran.

« Rends tout uniforme, genre tout symétrique. » SentriX affiche deux familles
d'écrans — les cartes classiques (utils/design_system) et les panneaux
Components V2 (utils/sentrix_panels) — et chacune avait SA table de couleurs.

Mesuré avant correction, sur les huit domaines connus des deux familles :
huit désaccords sur huit. La Sécurité était violette en carte et cyan en
panneau ; les Jeux, bleu nuit d'un côté et orange de l'autre.

Ces tests ne vérifient pas un goût, ils vérifient un accord : une seule table,
lue par les deux familles, et accordée aux bannières.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import couleurs_domaines as domaines  # noqa: E402
from utils import design_system, sentrix_panels as panels  # noqa: E402


def _couleur_de_carte(style) -> int:
    valeur = style["colour"]
    return int(getattr(valeur, "value", valeur))


def test_chaque_domaine_a_la_meme_couleur_dans_les_deux_familles():
    ecarts = []
    for nom, style in design_system.CATEGORY_STYLES.items():
        domaine = domaines.EQUIVALENCES.get(nom)
        if domaine is None or domaine not in panels.INTENTIONS:
            continue
        carte = _couleur_de_carte(style)
        panneau = panels.INTENTIONS[domaine][0]
        if carte != panneau:
            ecarts.append(f"{nom} : carte {carte:#08x} ≠ panneau {panneau:#08x}")
    assert not ecarts, "un domaine ne peut pas avoir deux couleurs :\n" + "\n".join(ecarts)


def test_les_deux_familles_lisent_bien_la_meme_table():
    """Égales par hasard ne suffit pas : elles doivent venir du même endroit."""
    for nom, domaine in domaines.EQUIVALENCES.items():
        if domaine not in panels.INTENTIONS or nom not in design_system.CATEGORY_STYLES:
            continue
        reference = domaines.DOMAINES[domaine]
        assert panels.INTENTIONS[domaine][0] == reference, domaine
        assert _couleur_de_carte(design_system.CATEGORY_STYLES[nom]) == reference, nom


def test_la_couleur_se_lit_par_son_nom_francais_ou_anglais():
    assert domaines.couleur("securite") == domaines.couleur("security")
    assert domaines.couleur("jeux") == domaines.couleur("games")
    # Un domaine inconnu ne fait pas tomber un écran : il prend la teinte neutre.
    assert domaines.couleur("domaine-qui-n-existe-pas") == 0x3B82F6


def test_les_etats_restent_ceux_de_config():
    """Réussite, erreur, avertissement : une seule source, config.py, déjà partagée."""
    import config

    assert panels.INTENTIONS["success"][0] == int(config.COLOR_SUCCESS)
    assert panels.INTENTIONS["danger"][0] == int(config.COLOR_ERROR)
    assert panels.INTENTIONS["warning"][0] == int(config.COLOR_WARNING)
    assert design_system.COLORS.success == int(config.COLOR_SUCCESS)
    assert design_system.COLORS.danger == int(config.COLOR_ERROR)


def test_chaque_domaine_garde_sa_banniere_accordee():
    """La couleur retenue est celle des bannières : le liseré doit suivre le trait."""
    familles = {
        "moderation": "moderation", "securite": "security", "tickets": "tickets",
        "economie": "economy", "niveaux": "levels", "musique": "music",
        "jeux": "games", "ia": "ai", "configuration": "config", "bienvenue": "welcome",
    }
    for domaine, famille in familles.items():
        assert panels.INTENTIONS[domaine] == (domaines.DOMAINES[domaine], famille), domaine
