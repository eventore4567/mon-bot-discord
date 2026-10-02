"""Une galerie de bannière ne part JAMAIS sans sa pièce jointe.

**Le bug de production, le 29/09/2026.** `/setup` répondait :

    Invalid Form Body
    In data.components.0.components.0.items.0.media.url:
    The referenced attachment ("attachment://banner_config.webp") was not found.

Ce n'est pas une image manquante : Discord **refuse le message entier**. La
commande ne répond plus du tout.

**La cause.** ``cogs/setup_invitations.final_send_setup`` est le dernier
expéditeur installé — c'est lui qui répond à ``/setup``. Il envoyait la vue
sans joindre la bannière que le conteneur référence. Trois autres expéditeurs
avaient été corrigés, pas celui-là, et rien ne pouvait le signaler : la galerie
est posée à la construction, la pièce jointe à l'envoi, à deux endroits
différents.

**Ce qui l'empêche de revenir.** Une condition unique,
``banniere_disponible()``, que la pose ET l'envoi consultent tous les deux.
Quand le fichier manque, ni la galerie ni la pièce jointe n'existent — l'écran
perd son bandeau mais reste affichable. Et aucun module ne construit sa
galerie à la main.
"""
from __future__ import annotations

import ast
import os
import pathlib

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[1]

#: Les modules qui posent une bannière sur un conteneur construit à la main.
MODULES_A_BANNIERE = (
    "cogs/setup_components_v73.py",
    "cogs/setup_experience_v74.py",
    "cogs/help_complete_v79.py",
    "cogs/setup_invitations.py",
)


def _source(chemin: str) -> str:
    return (RACINE / chemin).read_text(encoding="utf-8")


# =============================================================================
# La condition est unique
# =============================================================================

def test_la_pose_et_lenvoi_consultent_la_meme_condition():
    """C'est tout le correctif : deux décisions séparées peuvent diverger, une
    condition partagée ne le peut pas."""
    from cogs import setup_components_v73 as v73
    import inspect

    assert "banniere_disponible()" in inspect.getsource(v73.entete_banniere)
    assert "banniere_disponible()" in inspect.getsource(v73.joindre_banniere)


class _Conteneur:
    """Juste de quoi observer ce qu'on pose dessus."""

    def __init__(self):
        self.items = []

    def add_item(self, item):
        self.items.append(item)


def test_une_banniere_absente_est_regeneree(tmp_path, monkeypatch):
    """Sur Railway le dossier est VIDE après un déploiement : ``.gitignore``
    ignore ``banner_*.webp``, donc aucune bannière n'est versionnée.

    Un simple test d'existence aurait répondu « non » au premier /setup et
    l'écran serait parti sans bandeau — valide, mais nu. C'est la plainte
    « plein de trucs n'ont pas de bannière »."""
    from cogs import setup_components_v73 as v73
    from utils import log_banners

    monkeypatch.setattr(log_banners, "BANNER_DIR", tmp_path)
    monkeypatch.setattr(log_banners, "_READY", True)  # le cache mentirait

    assert list(tmp_path.iterdir()) == []
    assert v73.banniere_disponible() is True, "la bannière manquante n'a pas été générée"
    assert (tmp_path / log_banners.nom_fichier(v73.BANNIERE)).exists()
    assert v73.entete_banniere() is not None
    assert "file" in v73.joindre_banniere({"view": object()})


def test_si_la_generation_echoue_ni_galerie_ni_piece_jointe(tmp_path, monkeypatch):
    """Le cas qui faisait refuser le message ENTIER. Quand la bannière est
    hors d'atteinte, la galerie et la pièce jointe doivent disparaître
    ENSEMBLE — l'écran perd son bandeau mais reste affichable."""
    from cogs import setup_components_v73 as v73
    from utils import log_banners

    def _generation_impossible(force=False):
        raise OSError("disque en lecture seule")

    monkeypatch.setattr(log_banners, "BANNER_DIR", tmp_path)
    monkeypatch.setattr(log_banners, "ensure_banners", _generation_impossible)

    assert v73.banniere_disponible() is False
    assert v73.entete_banniere() is None
    assert "file" not in v73.joindre_banniere({"view": object()})

    conteneur = _Conteneur()
    v73.poser_banniere(conteneur)
    assert conteneur.items == [], "une galerie orpheline a été posée"


def test_avec_fichier_les_deux_sont_la():
    from cogs import setup_components_v73 as v73

    assert v73.banniere_disponible() is True
    assert v73.entete_banniere() is not None
    assert "file" in v73.joindre_banniere({"view": object()})


def test_le_nom_joint_est_celui_que_la_galerie_reference():
    """Une divergence de nom produit la même erreur Discord qu'une absence."""
    from cogs.setup_components_v73 import BANNIERE, joindre_banniere
    from utils.log_banners import nom_fichier

    fichier = joindre_banniere({"view": object()})["file"]
    assert fichier.filename == nom_fichier(BANNIERE)


def test_chaque_appel_rend_un_fichier_neuf():
    """Un discord.File consommé par un envoi arrive VIDE au suivant — donc une
    pièce jointe absente, donc le même refus."""
    from cogs.setup_components_v73 import joindre_banniere

    premier = joindre_banniere({"view": object()})["file"]
    second = joindre_banniere({"view": object()})["file"]
    assert premier is not second


# =============================================================================
# Aucun expéditeur ne peut oublier
# =============================================================================

#: Les façons légitimes de faire partir la pièce jointe avec la vue.
#: Toutes consultent la même condition que la pose du bandeau.
MOYENS_DE_JOINDRE = (
    "joindre_banniere",       # au moment de l'envoi
    "pieces_jointes_banniere",  # à la réédition de navigation
    "pieces_jointes_de_famille",
)


@pytest.mark.parametrize("chemin", MODULES_A_BANNIERE)
def test_tout_module_qui_pose_une_banniere_la_joint_aussi(chemin):
    """L'invariant qui ferme le bug : poser sans joindre fait refuser le
    message par Discord. ``setup_invitations`` posait la vue de V74 — donc une
    galerie — sans jamais joindre quoi que ce soit.

    Plusieurs moyens de joindre sont acceptés : un écran envoyé passe par
    ``joindre_banniere``, un écran réédité par ``pieces_jointes_banniere``.
    Ce qui est interdit, c'est de poser sans aucun des deux.
    """
    source = _source(chemin)
    if "poser_banniere(" not in source:
        pytest.skip(f"{chemin} ne pose aucun bandeau")
    assert any(moyen in source for moyen in MOYENS_DE_JOINDRE), (
        f"{chemin} pose une bannière sans jamais la joindre"
    )


#: Les seuls modules autorisés à composer ``attachment://banner...`` eux-mêmes.
#: Ailleurs, la galerie échapperait à la condition partagée.
POINTS_DENTREE_GALERIE = frozenset({"setup_components_v73.py"})


def test_aucun_module_ne_construit_sa_galerie_a_la_main():
    """Une galerie construite ailleurs échapperait à la condition partagée.

    Lu sur l'AST, et non par sous-chaîne : la version précédente accusait
    ``setup_invitations.py`` pour un COMMENTAIRE qui cite
    ``attachment://banner_config.webp`` en expliquant pourquoi il faut passer
    par le transport. Un test qui grep son propre voisinage finit par
    rougir sur de la prose.
    """
    coupables = []
    for fichier in sorted((RACINE / "cogs").glob("*.py")):
        if fichier.name in POINTS_DENTREE_GALERIE:
            continue
        try:
            arbre = ast.parse(fichier.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for noeud in ast.walk(arbre):
            # Seules les VRAIES chaînes comptent, pas les commentaires :
            # l'AST ne les conserve pas, ce qui supprime le faux positif.
            if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str):
                if "attachment://banner" in noeud.value:
                    coupables.append(fichier.name)
                    break
            elif isinstance(noeud, ast.JoinedStr):
                if "attachment://banner" in ast.unparse(noeud):
                    coupables.append(fichier.name)
                    break
    assert coupables == [], (
        f"ces modules composent une URL de bannière hors du point d'entrée : {coupables}"
    )


@pytest.mark.parametrize("chemin", MODULES_A_BANNIERE)
def test_aucun_envoi_de_vue_sans_passer_par_le_point_dentree(chemin):
    """Détecte un expéditeur oublié : ``send(view=...)`` sur une de ces vues
    doit passer par ``joindre_banniere``. C'est exactement ce qui manquait à
    setup_invitations."""
    arbre = ast.parse(_source(chemin))
    oublis = []
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call):
            continue
        nom = ast.unparse(noeud.func) if hasattr(ast, "unparse") else ""
        if not nom.endswith((".send", ".send_message")):
            continue
        rendu = ast.unparse(noeud)
        if "view=view" not in rendu and "view=vue" not in rendu:
            continue
        if "joindre_banniere" not in rendu:
            oublis.append(rendu[:70])
    assert oublis == [], f"{chemin} : envoi sans bannière jointe — {oublis}"
