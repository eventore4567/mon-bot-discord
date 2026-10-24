"""Un message MODIFIÉ passe les mêmes filtres qu'un nouveau message.

Avant : poster « salut » puis le transformer en invitation ou en lien
d'arnaque passait toutes les protections, AutoMod n'écoutant pas les
modifications.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import automod as automod_module  # noqa: E402
from tests.test_automod_spam_incident import _cog, _member, _message  # noqa: E402
from utils import sentrix_panels as panels  # noqa: E402


def _edit(cog, avant: str, apres: str):
    member = _member()
    before = _message(member, 1, avant)
    after = _message(member, 1, apres)
    before.content, after.content = avant, apres
    with patch.object(panels, "texte_court", AsyncMock()), \
         patch.object(automod_module, "INCIDENT_LOG_DELAY_SECONDS", 0.01):
        asyncio.run(cog.on_message_edit(before, after))
        asyncio.run(asyncio.sleep(0.05))
    return after


def test_une_invitation_ajoutee_en_modifiant_est_supprimee():
    cog = _cog(conf={"antiinvite": 1, "escalation": 0})
    after = _edit(cog, "salut tout le monde", "rejoignez https://discord.gg/abcdef")
    after.delete.assert_awaited_once()


def test_un_mot_interdit_ajoute_en_modifiant_est_supprime():
    cog = _cog(conf={"escalation": 0})
    cog.blacklist_words_cache[1] = ["arnaqueur"]
    after = _edit(cog, "bonjour", "bonjour arnaqueur")
    after.delete.assert_awaited_once()


def test_un_apercu_de_lien_sans_changement_de_texte_est_ignore():
    cog = _cog(conf={"antilink": 1, "escalation": 0})
    after = _edit(cog, "regarde https://exemple.com", "regarde https://exemple.com")
    after.delete.assert_not_awaited()


def test_une_correction_ne_compte_jamais_pour_l_anti_spam():
    cog = _cog(conf={"antispam": 1, "escalation": 1})
    for i in range(12):
        after = _edit(cog, f"bonjour {i}", f"bonjour {i} !")
        after.delete.assert_not_awaited()
    assert cog.spam_tracker.compter((1, 7), fenetre=60) == 0
