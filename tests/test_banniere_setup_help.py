"""+setup et +help portent leur bannière, comme le reste du bot.

Ces deux écrans étaient les deux derniers sans bannière : ils construisent
leurs conteneurs Components V2 à la main, avec une miniature, au lieu de
passer par ``panels.Panneau``.

**Le piège de ce lot, et il est silencieux.** Un ``discord.File`` porte un
curseur de lecture : une fois envoyé, il est consommé. Le réutiliser pour
l'édition suivante produit une pièce jointe VIDE — donc une galerie qui
référence ``attachment://banner_config.webp`` sans que ce fichier arrive, et
Discord affiche une image cassée sans la moindre erreur. Or ces vues se
réaffichent à CHAQUE clic de navigation en vidant leurs pièces jointes
(``attachments=[]``). Il faut donc refabriquer le fichier à chaque envoi et à
chaque édition.

**Le second piège, mesuré avant de le commettre.**
``panels.fichier_banniere(kind)`` re-décide la famille à partir de la commande
en cours. Hors commande — et une édition de navigation en est hors — il
retombe sur « info » et joint ``banner_info.webp`` alors que la galerie
référence ``banner_config.webp``. La bonne fonction pour une famille déjà
choisie est ``fichier_de_famille``, et son propre docstring prévient de ce
piège.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest


# =============================================================================
# Le fichier joint correspond à ce que la galerie référence
# =============================================================================

def test_le_fichier_joint_porte_le_nom_que_la_galerie_reference():
    """La divergence est invisible : Discord n'émet aucune erreur, il affiche
    simplement une image cassée."""
    from cogs.setup_components_v73 import BANNIERE, fichier_banniere
    from utils.log_banners import nom_fichier

    fichier = fichier_banniere()
    assert fichier is not None
    assert fichier.filename == nom_fichier(BANNIERE)


def test_chaque_appel_rend_un_fichier_neuf():
    """Un discord.File consommé par un envoi ne peut pas servir au suivant. Si
    cette fonction mettait son fichier en cache, la deuxième page de +setup
    arriverait avec une bannière vide."""
    from cogs.setup_components_v73 import fichier_banniere

    premier = fichier_banniere()
    second = fichier_banniere()
    assert premier is not second
    assert premier.filename == second.filename


def test_la_famille_nest_pas_redecidee_depuis_la_commande():
    """``fichier_banniere`` de panels re-décide la famille depuis le contexte
    de commande ; hors commande il rend « info ». C'est ce qui produisait
    banner_info.webp pour une galerie qui demande banner_config.webp."""
    import inspect

    from cogs import setup_components_v73 as v73

    source = inspect.getsource(v73.fichier_banniere)
    assert "fichier_de_famille" in source
    assert "from utils.sentrix_panels import fichier_banniere" not in source


def test_la_galerie_reference_bien_une_piece_jointe():
    import discord

    from cogs.setup_components_v73 import BANNIERE, entete_banniere
    from utils.log_banners import nom_fichier

    galerie = entete_banniere()
    assert isinstance(galerie, discord.ui.MediaGallery)
    rendu = str(galerie.to_component_dict())
    assert f"attachment://{nom_fichier(BANNIERE)}" in rendu


# =============================================================================
# Les deux écrans joignent réellement le fichier
# =============================================================================

@pytest.mark.parametrize("module,fonction", [
    ("cogs.setup_components_v73", "SentriXSetupV73.refresh"),
    ("cogs.help_complete_v79", None),
])
def test_les_editions_rejoignent_le_fichier(module, fonction):
    """``attachments=[]`` sur une édition retire la bannière du message. Les
    vues de navigation passent par là à chaque clic."""
    import importlib
    import inspect

    mod = importlib.import_module(module)
    source = inspect.getsource(mod)
    assert "attachments=[]" not in source or "attachments=[fichier]" in source, (
        "une édition vide encore ses pièces jointes sans rejoindre la bannière"
    )
    assert "fichier_banniere()" in source


def test_les_pages_de_v74_portent_la_banniere():
    """V74 hérite du refresh de V73 mais construit ses propres pages : elles
    doivent poser l'en-tête elles-mêmes.

    Ces deux tests ont échoué quand le correctif du 02/10/2026 a remplacé
    ``entete_banniere()`` par ``poser_banniere(container)`` : ils grepaient
    l'orthographe de l'appel, pas le comportement. Ils visent maintenant le
    point d'entrée, qui décide de poser ou non selon ``banniere_disponible()``.
    """
    import inspect

    from cogs import setup_experience_v74 as v74

    source = inspect.getsource(v74)
    conteneurs = source.count("discord.ui.Container(accent_colour=v73.ACCENT)")
    poses = source.count("v73.poser_banniere(")
    assert conteneurs >= 1
    assert poses == conteneurs, (
        f"{conteneurs} page(s) construites mais {poses} bannière(s) posée(s)"
    )


def test_lenvoi_initial_joint_la_banniere_sur_chaque_branche():
    """Trois branches d'envoi — Context, followup, réponse d'interaction — et
    aucune qui envoie la vue sans passer par le point d'entrée.

    C'est l'oubli exact qui a cassé ``/setup`` en production : une branche
    envoyait ``view=view`` sans joindre la bannière que le conteneur
    référence, et Discord refusait le message entier. La fraîcheur du fichier
    à chaque appel est vérifiée séparément, dans
    ``test_banniere_jamais_orpheline``.
    """
    import ast
    import inspect

    from cogs import setup_experience_v74 as v74

    arbre = ast.parse(inspect.getsource(v74))
    branches, oublis = 0, []
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call):
            continue
        appele = ast.unparse(noeud.func)
        if not appele.endswith((".send", ".send_message")):
            continue
        rendu = ast.unparse(noeud)
        if "view=view" not in rendu and "joindre_banniere" not in rendu:
            continue
        branches += 1
        if "joindre_banniere" not in rendu:
            oublis.append(rendu[:70])

    assert branches >= 3, f"{branches} branche(s) d'envoi trouvée(s), 3 attendues"
    assert oublis == [], f"branche(s) qui envoient sans la bannière : {oublis}"


# =============================================================================
# Le violet n'est plus l'accent de ces écrans
# =============================================================================

def test_laccent_nest_plus_violet():
    """Jayden : « enlève le style bleu violet, je veux une couleur simple, pas
    IA ». Cet accent alimente vingt et un écrans."""
    from cogs.setup_components_v73 import ACCENT

    assert ACCENT.value != 0x6D5DFB, "le violet est revenu"
    rouge, vert, bleu = ACCENT.r, ACCENT.g, ACCENT.b
    assert max(rouge, vert, bleu) - min(rouge, vert, bleu) <= 12, (
        f"l'accent est de nouveau teinté : {(rouge, vert, bleu)}"
    )


def test_laccent_est_le_meme_que_celui_de_la_carte():
    """Une seule palette pour tout le bot, pas une par module."""
    from cogs.setup_components_v73 import ACCENT

    assert ACCENT.value == 0xE6E8EC
