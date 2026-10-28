"""+modview et +staff : deux ou trois boutons visibles, le reste dans un menu.

28/10/2026 (brief V6, point 5) : chaque panneau affichait neuf boutons. Les
actions secondaires passent dans un menu qui doit appeler EXACTEMENT les mêmes
callbacks qu'avant — un bouton déplacé ne doit rien perdre.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from cogs import staff_suite


def _menu(vue):
    return next(item for item in vue.children if isinstance(item, discord.ui.Select))


def _boutons(vue):
    return [item.label for item in vue.children if isinstance(item, discord.ui.Button)]


def test_modview_deux_boutons_et_un_menu():
    async def scenario():
        vue = staff_suite.MemberPanelView(SimpleNamespace(), 1, 2)
        return vue, _boutons(vue), [o.value for o in _menu(vue).options]

    vue, boutons, options = asyncio.run(scenario())
    assert boutons == ["Historique", "Avertir"]
    assert options == ["sanctions", "note", "case", "watch", "mute", "kick", "ban"]


def test_modview_le_menu_ouvre_le_meme_formulaire_que_l_ancien_bouton():
    async def scenario():
        vue = staff_suite.MemberPanelView(SimpleNamespace(), 1, 2)
        menu = _menu(vue)
        menu._values = ["ban"]
        interaction = SimpleNamespace(response=SimpleNamespace(send_modal=AsyncMock()))
        await menu.callback(interaction)
        return interaction.response.send_modal

    send_modal = asyncio.run(scenario())
    modal = send_modal.await_args.args[0]
    assert isinstance(modal, staff_suite.MemberActionModal)


def test_centre_staff_trois_boutons_et_un_menu():
    async def scenario():
        vue = staff_suite.StaffCenterView(SimpleNamespace(), 1)
        return _boutons(vue), [o.value for o in _menu(vue).options]

    boutons, options = asyncio.run(scenario())
    assert boutons == ["Dossiers", "Incidents", "Urgence"]
    assert options == ["watches", "absences", "report", "handover", "diagnostic", "reminder"]
