"""Contrats production : slash /setup éphémère, états et pack d'emojis stable."""
from __future__ import annotations

import ast
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from sentrix_v95_runtime import _invoke_original
from utils import slash_catalog


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_slash_setup_ne_defer_jamais_publiquement():
    """Le vrai catalogue /setup contourne le Context préfixé et son defer public."""
    response = SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock(), is_done=lambda: False)
    interaction = SimpleNamespace(response=response)
    setup = SimpleNamespace(send_setup=AsyncMock())
    bot = SimpleNamespace(get_cog=lambda name: setup if name == "SentriXSetup" else None)
    command = SimpleNamespace(qualified_name="setup")
    await _invoke_original(bot, command, interaction, (), {})
    setup.send_setup.assert_awaited_once_with(interaction)
    response.defer.assert_not_awaited()
    response.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_slash_setup_indisponible_est_ephemere():
    response = SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock())
    interaction = SimpleNamespace(response=response)
    bot = SimpleNamespace(get_cog=lambda _name: None)
    await _invoke_original(bot, SimpleNamespace(qualified_name="setup"), interaction, (), {})
    response.send_message.assert_awaited_once_with(
        "Configuration momentanément indisponible.", ephemeral=True
    )
    response.defer.assert_not_awaited()


def test_setup_inclut_les_etats_et_la_banniere():
    src = (ROOT / "cogs/setup_experience_v74.py").read_text()
    a = src.index("    async def _build_home(self)")
    b = src.index("    async def _build_home_complet", a)
    accueil = src[a:b]
    assert "actifs_labels" in accueil
    assert "inactifs_labels" in accueil
    assert "manquants_labels" in accueil
    for status in ("Actifs :", "Désactivés :", "À configurer :"):
        assert status in accueil
    assert "v73.poser_banniere(container)" in accueil
    assert "sentrix_emojis.partiel(categories_emoji[key])" in accueil
    assert len({e.path for e in slash_catalog.CATALOG}) == len(slash_catalog.CATALOG)


def test_six_modules_importants_restent_accessibles():
    routes = {e.path for e in slash_catalog.CATALOG}
    assert {"setup", "ban", "warn", "clear", "tickets open", "logs search",
            "security antinuke", "music play", "duel fight"} <= routes


def test_lintercepteur_setup_se_compile():
    ast.parse((ROOT / "sentrix_v95_runtime.py").read_text())
