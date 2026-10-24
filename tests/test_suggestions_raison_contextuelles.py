"""Une option « raison » n'est pas toujours un motif de sanction.

Signalé par Jayden le 2026-10-16, capture à l'appui : ``/afk reason``
proposait « Propos haineux », « Usurpation d'identité », « Compte suspect
(raid) », « Contournement de sanction »… à quelqu'un qui part manger.

Cause : ``PAR_OPTION["raison"]`` appliquait les motifs de sanction à
TOUTE commande ayant une option de ce nom, sans regarder laquelle. Sur
les 21 commandes concernées, sept ne sanctionnent rien — /afk, /rep et
les crédits d'invitations.

Chaque famille reçoit donc sa propre liste, et une commande absente de
ces listes garde un champ libre sans suggestion : mieux vaut rien
proposer qu'une suggestion à côté de la plaque.
"""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from utils import slash_suggestions as ss


def _suggestions(chemin: str, saisie: str = "") -> list[str] | None:
    fournisseur = ss.PAR_COMMANDE.get((chemin, "raison"))
    if fournisseur is None:
        return None
    return [c.name for c in asyncio.run(fournisseur(None, saisie))]


def test_la_regle_generale_sur_le_nom_d_option_a_disparu():
    """C'est elle qui mettait des motifs de sanction sur /afk."""
    assert "raison" not in ss.PAR_OPTION


@pytest.mark.parametrize("chemin", [
    "ban", "unban", "kick", "warn", "timeout", "untimeout",
    "moderation hackban", "moderation tempban", "moderation lock",
    "security isolate", "protection block",
])
def test_les_commandes_qui_sanctionnent_gardent_les_motifs(chemin):
    suggestions = _suggestions(chemin)
    assert suggestions is not None, f"{chemin} ne propose plus rien"
    assert "Propos haineux" in suggestions


@pytest.mark.parametrize("chemin,attendu,interdit", [
    ("afk", "Repas", "Propos haineux"),
    ("rep give", "Merci pour l'aide", "Compte suspect (raid)"),
    ("invites bonus", "Récompense d'événement", "Usurpation d'identité"),
    ("invites deduct", "Invitations frauduleuses", "Contournement de sanction"),
])
def test_les_commandes_qui_ne_sanctionnent_rien_ont_leur_propre_liste(chemin, attendu, interdit):
    suggestions = _suggestions(chemin)
    assert suggestions is not None, f"{chemin} ne propose rien"
    assert attendu in suggestions
    assert interdit not in suggestions, f"{chemin} propose encore un motif de sanction"


@pytest.mark.parametrize("chemin", ["afk", "ban", "rep give", "invites bonus"])
def test_on_peut_toujours_ecrire_sa_propre_raison(chemin):
    """La question de Jayden : « si y'a pas ce qu'on veut on peut mettre la raison ? »

    Oui, et la saisie arrive en PREMIÈRE position — c'est ce que fait
    ``garder_saisie``. Une autocomplétion n'est jamais une liste fermée,
    contrairement à ``choices``.
    """
    suggestions = _suggestions(chemin, "ma raison bien à moi")
    assert suggestions[0] == "ma raison bien à moi"


def test_une_commande_sans_famille_ne_propose_rien_plutot_qu_a_cote():
    assert _suggestions("weather") is None
