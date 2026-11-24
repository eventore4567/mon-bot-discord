"""« donne le mess » lançait le jeu des portes mystères (24/11/2026).

En dernier recours, le routeur naturel demande au modèle de choisir une
commande parmi des candidates, et l'exécute si la confiance dépasse 78. Deux
failles : le préfiltre retenait ~20 commandes sur une simple ressemblance de
lettres, sans aucun mot commun, et rien ne vérifiait que la commande choisie
avait un rapport avec la phrase. Seuls les ARGUMENTS étaient ancrés.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from utils import ai_command_router as routeur  # noqa: E402


def _commande(nom, description, aliases=()):
    return SimpleNamespace(
        qualified_name=nom, name=nom, aliases=list(aliases), description=description,
        help="", signature="", hidden=False, enabled=True,
    )


DOORS = _commande("doors", "Choisir une des trois portes mystères et découvrir le trésor.")
CLASSEMENT = _commande("classement", "Afficher le classement du serveur.", aliases=("top",))


@pytest.mark.parametrize(("commande", "phrase", "attendu"), [
    (DOORS, "donne le mess", False),
    (DOORS, "donne le message", False),
    (DOORS, "lance les portes mystères", True),
    (DOORS, "joue a doors", True),
    (CLASSEMENT, "montre le top", True),
    (CLASSEMENT, "montre le classement", True),
    (CLASSEMENT, "le chat de la voisine", False),
])
def test_une_commande_doit_avoir_un_lien_reel_avec_la_phrase(commande, phrase, attendu):
    assert routeur.command_grounded_in_question(commande, phrase) is attendu


def test_le_prefiltre_ne_retient_plus_une_commande_sur_une_ressemblance_de_lettres():
    index = [(DOORS, "doors", {"doors", "choisir", "portes", "mysteres", "tresor"})]
    assert routeur.rank_command_candidates(index, "donne le mess") == []
    assert routeur.rank_command_candidates(index, "lance les portes mystères") == [DOORS]


def test_le_choix_du_modele_est_refuse_s_il_n_a_aucun_lien(monkeypatch):
    """L'incident exact : le modèle répond doors (confiance 95) à « donne le mess »."""
    from cogs import ai as ai_cog
    from utils import ai_service

    cog = ai_cog.Ai.__new__(ai_cog.Ai)
    cog._command_candidates = lambda question: [DOORS]
    monkeypatch.setattr(ai_service, "generate", AsyncMock(return_value=SimpleNamespace(
        ok=True, text='{"command": "doors", "arguments": "", "confidence": 95}',
    )))
    message = SimpleNamespace(guild=SimpleNamespace(id=1), channel=SimpleNamespace(id=2), author=SimpleNamespace(id=3))
    assert asyncio.run(cog._classify_existing_command(message, "donne le mess", "+")) is None
    assert asyncio.run(cog._classify_existing_command(message, "lance les portes mystères", "+")) == "+doors"
