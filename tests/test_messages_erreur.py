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
    """Rendu réel d'une erreur : une phrase courte pour une erreur simple, le texte
    complet du panneau compact pour une erreur technique inattendue."""
    texte = erreurs._texte_erreur_prefix(_FauxCtx(), erreur)
    if texte is None:
        return panels.texte_complet(erreurs._prefix_error_panel(_FauxCtx(), erreur)).casefold()
    return texte.casefold()


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
    assert "permission" in texte
    assert "gérer le serveur" in texte
    # une phrase, pas un panneau
    assert "\n" not in texte and len(texte) < 200


def test_forbidden_nomme_les_deux_causes_possibles():
    """La hierarchie des roles est la cause la plus frequente et la moins evidente."""
    texte = _rendu(discord.Forbidden.__new__(discord.Forbidden))
    assert "rôle sentrix" in texte
    assert "permission" in texte


def test_l_erreur_generique_donne_une_reference_sans_mentir_sur_l_etat():
    """Seule une erreur TECHNIQUE produit un panneau ; il porte la référence support
    et ne prétend plus « rien n'a été modifié » (faux quand l'action Discord avait
    déjà été appliquée avant l'exception)."""
    texte = _rendu(RuntimeError("boum"))
    assert "référence" in texte
    assert "sxr-" in texte
    assert "rien n'a été modifié" not in texte


def test_les_erreurs_simples_tiennent_en_une_phrase():
    ctx = _FauxCtx()
    param = type("P", (), {"name": "membre", "displayed_name": "membre"})()
    manquant = erreurs._texte_erreur_prefix(ctx, commands.MissingRequiredArgument(param))
    assert "« membre »" in manquant and "Usage : `+" in manquant
    assert erreurs._texte_erreur_prefix(ctx, commands.BadArgument("x")).startswith("L'argument")
    assert "1 et 100" in erreurs._texte_erreur_prefix(ctx, commands.RangeError(500, minimum=1, maximum=100))
    assert erreurs._texte_erreur_prefix(ctx, RuntimeError("boum")) is None


def test_aucun_message_d_erreur_ne_divulgue_d_information_technique():
    corps = _corps("_prefix_error_panel")
    for fuite in ("traceback", "Traceback", "__file__", "os.environ", "token"):
        assert fuite not in corps
