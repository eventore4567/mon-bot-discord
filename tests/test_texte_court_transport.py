"""panels.texte_court traverse la pile de transport SANS être promu en carte.

Trois couches promouvaient tout texte de commande en carte/embed :
final_interaction_policy (Context/Messageable/interaction/webhook), utils/command_visuals
(_styled_context_send) et utils/unified_command_panels — et production_embed_log_repair
remplaçait même final_interaction_policy._plain_root par « toujours False ». Une
confirmation courte de modération finissait donc en embed. La règle vit désormais à un
seul endroit (final_interaction_policy._plain_root + PLAIN_ROOTS) et lit le signal
panels.TEXTE_BRUT posé par texte_court.
"""
from __future__ import annotations

import inspect
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import final_interaction_policy as policy  # noqa: E402
from utils import command_visuals, sentrix_panels as panels, unified_command_panels  # noqa: E402


def test_une_seule_regle_plain_root():
    assert policy.PLAIN_ROOTS == frozenset({"verification"})
    assert policy._plain_root("verification") is True
    assert policy._plain_root("ban") is False
    assert policy._plain_root("sentrix") is False
    jeton = panels.TEXTE_BRUT.set(True)
    try:
        assert policy._plain_root("ban") is True
    finally:
        panels.TEXTE_BRUT.reset(jeton)
    # Plus aucune couche ne remplace _plain_root.
    from cogs import production_embed_log_repair
    import sentrix_verification_v96_finalizer as v96

    assert "policy._plain_root =" not in inspect.getsource(production_embed_log_repair)
    assert "policy._plain_root =" not in inspect.getsource(v96)


def test_les_couches_de_style_lisent_le_signal():
    assert "TEXTE_BRUT" in inspect.getsource(command_visuals._styled_context_send)
    assert "TEXTE_BRUT" in inspect.getsource(unified_command_panels._context_send)
    assert "TEXTE_BRUT" in inspect.getsource(unified_command_panels._interaction_send)
    assert "TEXTE_BRUT" in inspect.getsource(unified_command_panels._webhook_send)


@pytest.mark.asyncio
async def test_texte_court_pose_le_signal_pendant_l_envoi_et_le_retire_apres():
    vu = {}

    async def send(**kwargs):
        vu["pendant"] = panels.TEXTE_BRUT.get()
        vu["content"] = kwargs.get("content")
        return SimpleNamespace(id=1)

    ctx = SimpleNamespace(interaction=None, send=send)
    await panels.texte_court(ctx, "<@7> a été banni.")
    assert vu == {"pendant": True, "content": "<@7> a été banni."}
    assert panels.TEXTE_BRUT.get() is False


@pytest.mark.asyncio
async def test_payload_pages_laisse_le_texte_brut_intact():
    """Le point de conversion réel de final_interaction_policy : avec le signal posé, le
    contenu texte n'est pas transformé en embed."""
    jeton = panels.TEXTE_BRUT.set(True)
    try:
        pages = policy._payload_pages(("Bonjour",), {}, root="ban", force_embed=not policy._plain_root("ban"))
    finally:
        panels.TEXTE_BRUT.reset(jeton)
    assert pages == [(("Bonjour",), {})]
