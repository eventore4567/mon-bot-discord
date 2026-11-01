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
    assert "actifs =" in accueil
    assert "inactifs =" in accueil
    assert "incomplets =" in accueil
    for status in ("Actifs :", "Désactivés :", "À configurer :"):
        assert status in accueil
    assert "v73.poser_banniere(container)" in accueil
    assert "icons.partiel(icons_par_module.get(key" in accueil
    assert len({e.path for e in slash_catalog.CATALOG}) == len(slash_catalog.CATALOG)


def test_six_modules_importants_restent_accessibles():
    routes = {e.path for e in slash_catalog.CATALOG}
    assert {"setup", "ban", "warn", "clear", "tickets open", "logs search",
            "security antinuke", "music play", "duel fight"} <= routes


def test_lintercepteur_setup_se_compile():
    ast.parse((ROOT / "sentrix_v95_runtime.py").read_text())


def test_derniere_couche_invitations_ne_rend_jamais_setup_public():
    source = (ROOT / "cogs/setup_invitations.py").read_text()
    start = source.index("    async def final_send_setup(")
    end = source.index("    current = setup_ui.OfficialSetup.send_setup", start)
    transport = source[start:end]
    assert "ephemere=True" in transport
    assert "delete_after=15" in transport
    assert "panels.envoyer(target, view)" not in transport
    assert "target = target.interaction" in transport


def test_les_categories_ajoutees_nont_pas_de_keyerror_emoji():
    source = (ROOT / "cogs/setup_experience_v74.py").read_text()
    assert 'categories_emoji.get(key, "")' in source
    assert '"invitations": "tracking"' in source
    assert "details = await self._effective_states()" in source
