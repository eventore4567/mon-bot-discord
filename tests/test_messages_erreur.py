"""Les messages d'erreur doivent dire QUOI, POURQUOI et QUOI FAIRE.

Avant : « Permission requise : ban members. » — le nom brut de discord.py, en
anglais, que le lecteur doit traduire lui-meme. Et « Discord a refusé cette action »
sans indiquer la cause ni le remede.
"""
import ast
import pathlib

import pytest

from cogs.final_error_embed_v5 import _libelles
from utils.access_matrix import permission_label

import discord
from discord.ext import commands

from cogs import final_error_embed_v5 as erreurs
from utils import sentrix_panels as panels


class _FauxCtx:
    """Assez de surface pour construire un panneau d'erreur."""

    clean_prefix = "+"
    prefix = "+"
    invoked_with = "test"
    command = None
    guild = None


def _rendu(erreur) -> str:
    """Texte complet du panneau, comme il arriverait sur Discord.

    En minuscules : le renderer met les en-tetes de section en capitales, et
    figer cette decision de mise en forme dans chaque test la rendrait
    impossible a changer.
    """
    return panels.texte_complet(erreurs._prefix_error_panel(_FauxCtx(), erreur)).casefold()


ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "cogs" / "final_error_embed_v5.py").read_text(encoding="utf-8")


def _corps(nom: str) -> str:
    for node in ast.walk(ast.parse(SOURCE)):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == nom:
            return ast.unparse(node)
    raise AssertionError(f"{nom} introuvable")


@pytest.mark.parametrize("permission,attendu", [
    ("ban_members", "Bannir des membres"),
    ("kick_members", "Expulser des membres"),
    ("manage_roles", "Gérer les rôles"),
    ("moderate_members", "Exclure temporairement des membres"),
])
def test_les_permissions_sont_affichees_en_francais(permission, attendu):
    assert _libelles([permission]) == attendu


def test_plusieurs_permissions_forment_une_phrase():
    assert _libelles(["kick_members", "manage_roles"]) == "Expulser des membres et Gérer les rôles"
    assert _libelles(["ban_members", "kick_members", "manage_messages"]).count(",") == 1


def test_une_permission_inconnue_reste_lisible():
    """Jamais de snake_case affiche a un membre."""
    assert "_" not in permission_label("some_future_permission")
    assert permission_label("some_future_permission") == "Some future permission"


def test_une_liste_vide_ne_produit_pas_de_message_casse():
    assert _libelles([]) == "une permission supplémentaire"
    assert permission_label("") == "une permission"


def test_le_refus_de_permission_dit_quoi_faire():
    """On verifie le panneau REELLEMENT rendu, pas des tournures dans le source.

    Les messages sont maintenant composes en sections : chercher une phrase exacte
    dans le code casserait a chaque reformulation sans rien garantir a l'affichage.
    """
    texte = _rendu(commands.MissingPermissions(["manage_guild"]))
    assert "permission requise" in texte
    assert "comment l'obtenir" in texte
    assert "rôles" in texte
    assert "setup" in texte


def test_forbidden_nomme_les_deux_causes_possibles():
    """La hierarchie des roles est la cause la plus frequente et la moins evidente."""
    texte = _rendu(discord.Forbidden.__new__(discord.Forbidden))
    assert "causes possibles" in texte
    assert "hiérarchie" in texte
    assert "remontez le rôle" in texte


def test_l_erreur_generique_rassure_sur_l_etat_du_serveur():
    """« Une erreur est survenue » laisse craindre une action a moitie appliquee.

    L'information a maintenant sa propre section, « Ce qui s'est passé », au lieu
    d'etre une phrase perdue dans un paragraphe.
    """
    texte = _rendu(RuntimeError("boum"))
    assert "ce qui s'est passé" in texte
    assert "rien n'a été modifié" in texte


def test_aucun_message_d_erreur_ne_divulgue_d_information_technique():
    corps = _corps("_prefix_error_panel")
    for fuite in ("traceback", "Traceback", "__file__", "os.environ", "token"):
        assert fuite not in corps
