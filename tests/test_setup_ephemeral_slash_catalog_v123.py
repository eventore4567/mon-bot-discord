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
    response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    response.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_slash_setup_indisponible_est_ephemere():
    response = SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock(), is_done=lambda: False)
    followup = SimpleNamespace(send=AsyncMock())
    interaction = SimpleNamespace(response=response, followup=followup)
    bot = SimpleNamespace(get_cog=lambda _name: None)
    await _invoke_original(bot, SimpleNamespace(qualified_name="setup"), interaction, (), {})
    followup.send.assert_awaited_once_with(
        "Configuration momentanément indisponible.", ephemeral=True
    )
    response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    response.send_message.assert_not_awaited()


def test_setup_inclut_les_etats_et_la_banniere():
    src = (ROOT / "cogs/setup_experience_v74.py").read_text()
    a = src.index("    async def _build_home(self)")
    b = src.index("    def _nom_cle", a)
    accueil = src[a:b]
    # 22/11/2026 : « refais tout le setup, plus simple ». L'accueil n'a plus le menu
    # unique de 22 entrées : six sections (SECTIONS) mènent aux mêmes pages.
    # L'état reste visible : modules actifs, à terminer, et protections.
    assert "actifs =" in accueil
    assert "a_terminer =" in accueil
    assert "protegees =" in accueil
    assert "À terminer" in accueil
    assert "v73.poser_banniere(container)" in accueil
    # 23/11/2026 : chaque fiche de section porte son icône (ICONES_SECTIONS).
    assert "ICONES_SECTIONS.get(cle" in accueil
    assert len({e.path for e in slash_catalog.CATALOG}) == len(slash_catalog.CATALOG)


def test_six_modules_importants_restent_accessibles():
    routes = {e.path for e in slash_catalog.CATALOG}
    assert {"setup", "ban", "warn", "clear", "tickets open", "logs search",
            "security antinuke", "music play", "play trivia"} <= routes


def test_lintercepteur_setup_se_compile():
    ast.parse((ROOT / "sentrix_v95_runtime.py").read_text())


def test_derniere_couche_invitations_separe_prefix_public_et_slash_prive():
    source = (ROOT / "cogs/setup_invitations.py").read_text()
    start = source.index("    async def final_send_setup(")
    end = source.index("    current = setup_ui.OfficialSetup.send_setup", start)
    transport = source[start:end]
    assert "return await panels.envoyer(target, view, ephemere=False)" in transport
    assert "return await panels.envoyer(target, view, ephemere=True)" in transport
    assert "return await panels.envoyer(target.followup, view, ephemere=True)" in transport
    # 05/11/2026 : /setup s'ouvre pour tous (lecture) ; chaque clic est contrôlé par
    # SentriXSetupV73.interaction_check (peut_configurer), plus par _can_setup à l'ouverture.
    assert "await setup_ui._can_setup(self.bot, member, guild)" not in transport
    assert "if guild is None or member is None" in transport
    assert "PrivateSetupLauncher" not in source
    assert "delete_after=15" not in transport


def test_les_categories_ajoutees_nont_pas_de_keyerror_emoji():
    # 22/11/2026 : chaque SECTION porte son icône ; les invitations sont rangées
    # dans « Modération » et l'état détaillé est toujours lu.
    from cogs import setup_experience_v74 as v74

    source = (ROOT / "cogs/setup_experience_v74.py").read_text()
    assert all(section[3] for section in v74.SECTIONS)
    assert any("invitations" in section[6] for section in v74.SECTIONS)
    assert "etats_detail = await self._effective_states()" in source


