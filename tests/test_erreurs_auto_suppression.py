"""Un message d'erreur qui reste affiché indéfiniment encombre le salon.

La personne corrige, réessaie, et l'ancien message d'erreur traîne encore.
Ce test vérifie que les six chemins d'envoi programment une suppression :
directement via delete_after quand la surface le permet (Messageable.send,
InteractionResponse.send_message, Message.edit), sinon en programmant la
suppression à la main sur le message renvoyé (edit_original_response,
Webhook.send, qui n'exposent pas delete_after).
"""
from __future__ import annotations

import ast
import os
import pathlib

os.environ.setdefault("DISCORD_TOKEN", "x")
RACINE = pathlib.Path(__file__).resolve().parent.parent
SOURCE = (RACINE / "cogs" / "final_error_embed_v5.py").read_text(encoding="utf-8")


def _corps(nom: str) -> str:
    for node in ast.walk(ast.parse(SOURCE)):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == nom:
            return ast.unparse(node)
    raise AssertionError(f"{nom} introuvable")


def test_le_delai_est_raisonnable_pour_lire_une_erreur_detaillee():
    assert "_DUREE_AFFICHAGE = 30" in SOURCE


def test_l_envoi_prefixe_programme_sa_propre_suppression():
    assert "delete_after" in _corps("_raw_prefix_send")


def test_le_remplacement_d_une_reponse_prefixee_programme_sa_suppression():
    assert "delete_after" in _corps("_replace_prefix_response")


def test_les_branches_slash_qui_envoient_une_erreur_programment_une_suppression():
    corps = _corps("_raw_slash_send")
    # Réponse différée : edit_original_response ne possède pas delete_after.
    assert corps.count("_effacer_plus_tard") == 1
    # Réponse fraîche : send_message gère directement le délai.
    assert "delete_after" in corps
    # Une vraie réponse déjà envoyée est conservée : aucune erreur tardive ne
    # remplace un succès ni ne crée un follow-up parasite.
    assert "résultat utilisateur conservé" in corps


def test_le_helper_de_suppression_differee_est_silencieux_sur_l_echec():
    corps = _corps("_effacer_plus_tard")
    assert "discord.NotFound" in corps
    assert "delete(delay=_DUREE_AFFICHAGE)" in corps
