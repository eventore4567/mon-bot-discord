"""Contrats de présentation des refus de hiérarchie dans SentriX."""
from __future__ import annotations
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
import pytest
from cogs.moderation import Moderation
from cogs import moderation as moderation_module
from utils import sentrix_panels as panels


def test_memoire_et_reference_sur_des_lignes_distinctes():
    rendu = panels._pied_avec_memoire_separee(
        "-# Modération · Hiérarchie des rôles · Réf. SX-QCC4WAT",
        "Réf. SX-QCC4WAT",
        "sur le serveur depuis 18 j",
    )
    assert rendu.splitlines() == [
        "-# Modération · Hiérarchie des rôles",
        "-# sur le serveur depuis 18 j",
        "-# Réf. SX-QCC4WAT",
    ]
    assert "j · Réf." not in rendu


@pytest.mark.asyncio
async def test_nickname_refus_hierarchie_en_panneau():
    cog = Moderation.__new__(Moderation)
    cog._ack = AsyncMock()
    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=42),
        author=SimpleNamespace(id=12),
        interaction=object(),
    )
    target = SimpleNamespace(id=34, edit=AsyncMock())
    erreur = "SentriX ne peut pas sanctionner ce membre : son rôle le plus élevé est au-dessus de celui de SentriX."

    with patch.object(moderation_module.checks, "check_hierarchy", return_value=None), patch.object(
        moderation_module.checks, "check_bot_hierarchy", return_value=erreur
    ), patch.object(panels, "envoyer", AsyncMock()) as envoyer, patch.object(
        panels, "texte_court", AsyncMock()
    ) as texte_court:
        await Moderation.nickname.callback(cog, ctx, target, pseudo="Surnom")

    target.edit.assert_not_awaited()
    envoyer.assert_awaited_once()
    assert envoyer.await_args.kwargs["ephemere"] is True
    assert "Comment corriger" in panels.texte_complet(envoyer.await_args.args[1])
    texte_court.assert_not_awaited()
